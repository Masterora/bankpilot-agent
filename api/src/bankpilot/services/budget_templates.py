"""Deterministic preview, locked writes and recoverable template application."""

import hashlib
import json
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.budget_template_repository import TemplateRepository
from bankpilot.db.models import BudgetRecord, BudgetTemplateApplicationRecord, BudgetTemplateRecord
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.budget_templates import (
    TemplateApply,
    TemplateChange,
    TemplateInput,
    TemplatePreview,
    TemplateTarget,
    TemplateView,
)
from bankpilot.errors import PlanningError
from bankpilot.services.attention import synchronize_existing_states


def view(row: BudgetTemplateRecord) -> TemplateView:
    return TemplateView(
        id=row.id,
        name=row.name,
        entries=row.entries,
        expected_version=row.version,
        version=row.version,
    )


async def save(session: AsyncSession, uid: UUID, payload: TemplateInput) -> TemplateView:
    await UserRepository(session).lock(uid)
    repo = TemplateRepository(session)
    row = await repo.get(uid, payload.id)
    entries = [e.model_dump(mode="json") for e in payload.entries]
    if (
        row
        and row.name == payload.name
        and row.entries == entries
        and row.version == payload.expected_version + 1
    ):
        return view(row)  # Exact lost-response retry; never upgrades a changed draft.
    if (row.version if row else 0) != payload.expected_version:
        raise PlanningError("planning_stale")
    if row:
        row.name, row.entries, row.version = payload.name, entries, row.version + 1
    else:
        if len(await repo.items(uid)) >= 20:
            raise PlanningError("template_capacity", 422)
        row = BudgetTemplateRecord(
            user_id=uid, id=payload.id, name=payload.name, entries=entries, version=1
        )
        session.add(row)
    await session.flush()
    return view(row)


async def remove(session: AsyncSession, uid: UUID, tid: UUID, version: int) -> None:
    await UserRepository(session).lock(uid)
    row = await TemplateRepository(session).get(uid, tid)
    if not row:
        raise PlanningError("planning_not_found", 404)
    if row.version != version:
        raise PlanningError("planning_stale")
    await session.delete(row)


async def load_target(
    session: AsyncSession, uid: UUID, tid: UUID, month: date
) -> tuple[TemplateView, dict[tuple[str, str], BudgetRecord]]:
    row = await TemplateRepository(session).get(uid, tid)
    if row is None:
        raise PlanningError("planning_not_found", 404)
    budgets = {
        (b.category, b.currency): b for b in await PlanningRepository(session).budgets(uid, month)
    }
    return view(row), budgets


async def preview(
    session: AsyncSession, uid: UUID, tid: UUID, target: TemplateTarget
) -> TemplatePreview:
    template, budgets = await load_target(session, uid, tid, target.month)
    return build_preview(uid, template, target, budgets)


def build_preview(
    uid: UUID,
    template: TemplateView,
    target: TemplateTarget,
    budgets: dict[tuple[str, str], BudgetRecord],
) -> TemplatePreview:
    changes = []
    identities = []
    for entry in template.entries:
        existing = budgets.get((entry.category.value, entry.currency))
        keep = existing is not None and (
            target.mode == "missing" or existing.amount == entry.amount
        )
        changes.append(
            TemplateChange(
                category=entry.category,
                currency=entry.currency,
                before=existing.amount if existing else None,
                after=existing.amount if keep and existing else entry.amount,
                action="keep" if keep else "replace" if existing else "create",
            )
        )
        identities.append((str(existing.id), existing.version) if existing else None)
    material = {
        "uid": str(uid),
        "template": template.model_dump(mode="json"),
        "target": target.model_dump(mode="json"),
        "identities": identities,
        "changes": [c.model_dump(mode="json") for c in changes],
    }
    fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    return TemplatePreview(
        **target.model_dump(),
        template_id=template.id,
        template_name=template.name,
        template_version=template.version,
        fingerprint=fingerprint,
        changes=changes,
    )


async def apply(
    session: AsyncSession, uid: UUID, tid: UUID, payload: TemplateApply
) -> TemplatePreview:
    await UserRepository(session).lock(uid)
    repo = TemplateRepository(session)
    prior = await repo.receipt(uid, payload.operation_id)
    if prior:
        receipt = TemplatePreview.model_validate(prior.receipt)
        if (
            prior.template_id != tid
            or receipt.month != payload.month
            or receipt.mode != payload.mode
            or receipt.fingerprint != payload.fingerprint
        ):
            raise PlanningError("planning_stale")
        return receipt
    count = await session.scalar(
        select(func.count())
        .select_from(BudgetTemplateApplicationRecord)
        .where(BudgetTemplateApplicationRecord.user_id == uid)
    )
    if count is not None and count >= 1000:
        raise PlanningError("template_capacity", 422)
    target = TemplateTarget(month=payload.month, mode=payload.mode)
    template, budgets = await load_target(session, uid, tid, target.month)
    result = build_preview(uid, template, target, budgets)
    if result.fingerprint != payload.fingerprint:
        raise PlanningError("planning_stale")
    for change in result.changes:
        if change.action == "keep":
            continue
        row = budgets.get((change.category.value, change.currency))
        if row:
            row.amount = change.after
            row.version += 1
        else:
            session.add(
                BudgetRecord(
                    user_id=uid,
                    month=payload.month,
                    category=change.category.value,
                    currency=change.currency,
                    amount=change.after,
                )
            )
    await session.flush()
    await synchronize_existing_states(session, uid, months={payload.month}, source_type="budget")
    result.applied = True
    session.add(
        BudgetTemplateApplicationRecord(
            user_id=uid,
            operation_id=payload.operation_id,
            template_id=tid,
            receipt=result.model_dump(mode="json"),
        )
    )
    await session.flush()
    return result
