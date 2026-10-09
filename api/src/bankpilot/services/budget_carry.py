"""Explicit carryover using shared spending facts, user locks and frozen receipts."""

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import BudgetCarryRecord, BudgetRecord
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import BudgetCarryInput, BudgetCarryItem, BudgetCarryPreview
from bankpilot.errors import PlanningError
from bankpilot.services.attention import synchronize_existing_states
from bankpilot.services.planning_reads import planning_today
from bankpilot.services.spending import CALCULATION_VERSION, read_spending


async def preview_carry(session: AsyncSession, uid: UUID, month: date) -> BudgetCarryPreview:
    if month.day != 1 or not date(1900, 2, 1) <= month <= planning_today().replace(day=1):
        raise PlanningError("budget_carry_month", 422)
    stored = await session.get(BudgetCarryRecord, (uid, month))
    if stored:
        return BudgetCarryPreview.model_validate(stored.receipt)
    source_month = (month - timedelta(days=1)).replace(day=1)
    repo = PlanningRepository(session)
    source = await repo.budgets(uid, source_month)
    targets = {(r.category, r.currency): r for r in await repo.budgets(uid, month)}
    calculation = await read_spending(session, uid, source_month)
    items = []
    identities = []
    for row in source:
        spent = calculation.totals.get((row.category, row.currency), Decimal("0.00"))
        carry = max(Decimal("0.00"), row.amount - max(Decimal("0.00"), spent))
        target = targets.get((row.category, row.currency))
        base = target.amount if target else row.amount
        if carry == 0:
            continue
        if base + carry > Decimal("9999999999999999.99"):
            raise PlanningError("budget_carry_amount_limit", 422)
        items.append(
            BudgetCarryItem(
                category=TransactionCategory(row.category),
                currency=row.currency,
                source_amount=row.amount,
                source_spent=spent,
                source_transaction_count=len(calculation.imported_dates.get(row.currency, [])),
                base_amount=base,
                carry_amount=carry,
                target_amount=base + carry,
            )
        )
        identities.append(
            (row.id, row.version, target.id if target else None, target.version if target else 0)
        )
    material = {
        "user": str(uid),
        "month": str(month),
        "calculation": CALCULATION_VERSION,
        "rule": "carry-v1",
        "ledger_revision": calculation.ledger_revision,
        "identities": identities,
        "items": [item.model_dump(mode="json") for item in items],
    }
    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode()
    ).hexdigest()
    return BudgetCarryPreview(
        month=month, source_month=source_month, fingerprint=fingerprint, items=items
    )


async def confirm_carry(
    session: AsyncSession,
    uid: UUID,
    payload: BudgetCarryInput,
) -> BudgetCarryPreview:
    await UserRepository(session).lock(uid)
    prior = await session.scalar(
        select(BudgetCarryRecord).where(
            BudgetCarryRecord.user_id == uid,
            BudgetCarryRecord.operation_id == payload.operation_id,
        )
    )
    if prior:
        if prior.month != payload.month or prior.fingerprint != payload.fingerprint:
            raise PlanningError("planning_conflict")
        return BudgetCarryPreview.model_validate(prior.receipt)
    preview = await preview_carry(session, uid, payload.month)
    if preview.applied:
        raise PlanningError("budget_carry_applied")
    if preview.fingerprint != payload.fingerprint:
        raise PlanningError("planning_stale")
    if not preview.items:
        raise PlanningError("budget_carry_empty", 422)
    repo = PlanningRepository(session)
    for item in preview.items:
        record = await repo.budget(uid, payload.month, item.category.value, item.currency)
        if record:
            record.amount = item.target_amount
            record.version += 1
        else:
            repo.add(
                BudgetRecord(
                    user_id=uid,
                    month=payload.month,
                    category=item.category.value,
                    currency=item.currency,
                    amount=item.target_amount,
                )
            )
    preview.applied = True
    preview.operation_id = payload.operation_id
    session.add(
        BudgetCarryRecord(
            user_id=uid,
            month=payload.month,
            operation_id=payload.operation_id,
            fingerprint=payload.fingerprint,
            receipt=preview.model_dump(mode="json"),
        )
    )
    await session.flush()
    await synchronize_existing_states(session, uid, months={payload.month}, source_type="budget")
    return preview
