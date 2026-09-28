"""Build and mutate deterministic attention items without delegating authority to a model."""

from __future__ import annotations

import hashlib
from dataclasses import fields
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.attention_repository import AttentionRepository
from bankpilot.db.models import (
    AttentionOperationRecord,
    AttentionPreferenceRecord,
    AttentionStateRecord,
)
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.attention import (
    BUSINESS_ZONE,
    AttentionFact,
    AttentionGroup,
    AttentionItem,
    AttentionPreference,
    AttentionPreferenceInput,
    AttentionReceipt,
    AttentionSource,
    AttentionState,
    AttentionStateInput,
    AttentionType,
    canonical_json,
    fact_token,
    project_attention,
    snooze_deadline,
    state_version,
)
from bankpilot.domain.planning import BudgetItem, RecurringOccurrence
from bankpilot.errors import PlanningError
from bankpilot.services.planning_reads import RecurringSource, budget_items, read_recurring_month
from bankpilot.services.spending import read_spending

GROUP_TYPES: dict[str, tuple[AttentionType, ...]] = {
    "budget": (
        AttentionType.BUDGET_NEAR_LIMIT,
        AttentionType.BUDGET_LIMIT_REACHED,
        AttentionType.BUDGET_OVERSPENT,
    ),
    "recurring": (
        AttentionType.RECURRING_UPCOMING,
        AttentionType.RECURRING_UNREVIEWED,
        AttentionType.RECURRING_REVIEW_REQUIRED,
    ),
}


def budget_fact(item: BudgetItem, month: date) -> AttentionFact:
    kind: AttentionType | None = None
    if item.spent > item.amount:
        kind = AttentionType.BUDGET_OVERSPENT
    elif item.spent == item.amount:
        kind = AttentionType.BUDGET_LIMIT_REACHED
    elif item.spent >= item.amount * Decimal("0.8"):
        kind = AttentionType.BUDGET_NEAR_LIMIT
    return AttentionFact(
        "budget",
        item.id,
        month,
        kind,
        item.category.value,
        item.category.value,
        item.currency,
        item.amount,
        item.spent,
    )


def recurring_fact(
    item: RecurringSource, occurrence: RecurringOccurrence, today: date
) -> AttentionFact:
    kind: AttentionType | None = None
    if not occurrence.skipped:
        if occurrence.transaction and not occurrence.transaction.eligible:
            kind = AttentionType.RECURRING_REVIEW_REQUIRED
        elif occurrence.transaction is None:
            kind = (
                AttentionType.RECURRING_UPCOMING
                if occurrence.due_date > today
                else AttentionType.RECURRING_UNREVIEWED
            )
    return AttentionFact(
        "recurring",
        item.plan.id,
        occurrence.due_date,
        kind,
        item.plan.name,
        None,
        item.config.currency,
        item.config.amount,
        None,
    )


async def facts_for_group(
    session: AsyncSession,
    user_id: UUID,
    month: date,
    source_type: str,
    now: datetime | None = None,
) -> dict[tuple[UUID, date], AttentionFact]:
    if source_type == "budget":
        budgets = await PlanningRepository(session).budgets(user_id, month)
        calculation = await read_spending(session, user_id, month)
        facts = [budget_fact(item, month) for item in budget_items(budgets, calculation)]
    else:
        recurring_data = await read_recurring_month(
            session, user_id, month, include_candidates=False
        )
        today = (now or datetime.now(UTC)).astimezone(BUSINESS_ZONE).date()
        facts = [
            recurring_fact(item, occurrence, today)
            for item in recurring_data.sources
            for occurrence in item.occurrences
        ]
    return {(fact.source_id, fact.source_date): fact for fact in facts}


STATE_FIELDS = tuple(field.name for field in fields(AttentionState) if field.name != "expired")


def _stored(row: AttentionStateRecord | None) -> AttentionState | None:
    return AttentionState(**{name: getattr(row, name) for name in STATE_FIELDS}) if row else None


def _apply(row: AttentionStateRecord, state: AttentionState) -> None:
    for name in STATE_FIELDS:
        setattr(row, name, getattr(state, name))


async def read_preferences(session: AsyncSession, user_id: UUID) -> list[AttentionPreference]:
    rows = await AttentionRepository(session).preferences(user_id)
    stored = {row.attention_type: row for row in rows}
    return [
        AttentionPreference(
            attention_type=kind,
            enabled=stored[kind.value].enabled if kind.value in stored else True,
            version=stored[kind.value].version if kind.value in stored else 0,
        )
        for kind in AttentionType
    ]


def _item(
    user_id: UUID, fact: AttentionFact, row: AttentionStateRecord | None, now: datetime
) -> AttentionItem:
    projection = project_attention(_stored(row), fact, now)
    return AttentionItem(
        source=AttentionSource(
            source_type=fact.source_type, source_id=fact.source_id, source_date=fact.source_date
        ),
        attention_type=cast(AttentionType, fact.attention_type),
        state=cast(Literal["unread", "read", "snoozed"], projection.state),
        fact_token=fact_token(user_id, fact, projection.generation),
        state_version=state_version(projection.revision, expired=projection.expired),
        title=fact.title,
        category=fact.category,
        currency=fact.currency,
        amount=fact.amount,
        current_amount=fact.current_amount,
        snoozed_until=projection.snoozed_until,
        tracking_gap=projection.last_tracking_gap,
    )


async def read_group(
    session: AsyncSession, user_id: UUID, month: date, source_type: str, now: datetime
) -> AttentionGroup:
    facts = await facts_for_group(session, user_id, month, source_type, now)
    repo = AttentionRepository(session)
    rows = await repo.states(user_id, month=month, source_type=source_type)
    states = {(row.source_id, row.source_date): row for row in rows}
    preferences = [
        item
        for item in await read_preferences(session, user_id)
        if item.attention_type in GROUP_TYPES[source_type]
    ]
    enabled = {item.attention_type.value: item.enabled for item in preferences}
    result = AttentionGroup(status="ready", read_at=now, preferences=preferences)
    for fact in sorted(facts.values(), key=lambda value: (value.source_date, value.source_id.int)):
        if not fact.active:
            continue
        item = _item(user_id, fact, states.get((fact.source_id, fact.source_date)), now)
        if not enabled[item.attention_type.value]:
            result.disabled_count += 1
        elif item.state == "read":
            result.read.append(item)
        elif item.state == "snoozed":
            result.snoozed.append(item)
        else:
            result.unread.append(item)
    return result


def _digest(payload: object) -> str:
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


async def _replay(
    repo: AttentionRepository, user_id: UUID, operation_id: UUID, digest: str
) -> AttentionReceipt | None:
    operation = await repo.operation(user_id, operation_id)
    if operation is None:
        return None
    if operation.request_digest != digest:
        raise PlanningError("attention_operation_conflict", 409)
    return AttentionReceipt.model_validate(operation.receipt)


async def change_state(
    session: AsyncSession,
    user_id: UUID,
    payload: AttentionStateInput,
    now: datetime,
) -> AttentionReceipt:
    await UserRepository(session).lock(user_id)
    repo = AttentionRepository(session)
    digest = _digest(payload)
    replay = await _replay(repo, user_id, payload.operation_id, digest)
    if replay:
        return replay
    month = payload.source_date.replace(day=1)
    facts = await facts_for_group(session, user_id, month, payload.source_type, now)
    fact = facts.get((payload.source_id, payload.source_date))
    if fact is None or not fact.active:
        raise PlanningError("attention_not_found", 404)
    row = await repo.state(user_id, payload.source_type, payload.source_id, payload.source_date)
    projection = project_attention(_stored(row), fact, now)
    if payload.fact_token != fact_token(user_id, fact, projection.generation):
        raise PlanningError("attention_stale", 409)
    if payload.expected_state_version != state_version(
        projection.revision, expired=projection.expired
    ):
        raise PlanningError("attention_state_conflict", 409)
    if payload.action == "snooze" and payload.snooze_option is None:
        raise PlanningError("invalid_snooze_time", 422)
    if payload.action != "snooze" and payload.snooze_option is not None:
        raise PlanningError("invalid_snooze_time", 422)
    if row is None:
        row = AttentionStateRecord(
            user_id=user_id,
            source_type=fact.source_type,
            source_id=fact.source_id,
            source_date=fact.source_date,
        )
        repo.add(row)
    _apply(row, projection)
    row.revision += 1
    row.state_attention_type = cast(AttentionType, fact.attention_type).value
    if payload.action == "read":
        row.state, row.snoozed_until = "read", None
    elif payload.action == "restore":
        row.state, row.snoozed_until = "unread", None
    else:
        try:
            deadline = snooze_deadline(cast(str, payload.snooze_option), now)
        except (OverflowError, ValueError) as exc:
            raise PlanningError("invalid_snooze_time", 422) from exc
        row.state, row.snoozed_until = "snoozed", deadline
    receipt = AttentionReceipt(
        operation_id=payload.operation_id,
        accepted_version=state_version(row.revision),
        snoozed_until=row.snoozed_until,
    )
    repo.add(
        AttentionOperationRecord(
            user_id=user_id,
            operation_id=payload.operation_id,
            request_digest=digest,
            receipt=receipt.model_dump(mode="json"),
        )
    )
    return receipt


async def change_preference(
    session: AsyncSession,
    user_id: UUID,
    attention_type: AttentionType,
    payload: AttentionPreferenceInput,
) -> AttentionReceipt:
    await UserRepository(session).lock(user_id)
    repo = AttentionRepository(session)
    digest = _digest({"attention_type": attention_type.value, **payload.model_dump(mode="json")})
    replay = await _replay(repo, user_id, payload.operation_id, digest)
    if replay:
        return replay
    row = await repo.preference(user_id, attention_type.value)
    if payload.expected_version != (row.version if row else 0):
        raise PlanningError("attention_preference_conflict", 409)
    if row is None:
        row = AttentionPreferenceRecord(
            user_id=user_id, attention_type=attention_type.value, enabled=payload.enabled, version=1
        )
        repo.add(row)
    else:
        row.enabled = payload.enabled
        row.version += 1
    receipt = AttentionReceipt(operation_id=payload.operation_id, accepted_version=str(row.version))
    repo.add(
        AttentionOperationRecord(
            user_id=user_id,
            operation_id=payload.operation_id,
            request_digest=digest,
            receipt=receipt.model_dump(mode="json"),
        )
    )
    return receipt


async def synchronize_ledger(session: AsyncSession, user_id: UUID, ids: set[UUID]) -> None:
    await session.flush()
    months = await AttentionRepository(session).affected_months(user_id, ids)
    await synchronize_existing_states(session, user_id, months=months)


async def synchronize_existing_states(
    session: AsyncSession,
    user_id: UUID,
    now: datetime | None = None,
    *,
    months: set[date] | None = None,
    source_type: str | None = None,
    source_id: UUID | None = None,
) -> None:
    """Persist transitions for already-handled sources inside the caller's business transaction."""
    now = now or datetime.now(UTC)
    repo = AttentionRepository(session)
    if months is None and source_id is None:
        raise ValueError("Attention synchronization requires an explicit impact scope")
    rows = await repo.states(user_id, months=months, source_type=source_type, source_id=source_id)
    grouped: dict[tuple[str, date], list[AttentionStateRecord]] = {}
    for row in rows:
        grouped.setdefault((row.source_type, row.source_date.replace(day=1)), []).append(row)
    for (source_type, month), group in grouped.items():
        try:
            facts = await facts_for_group(session, user_id, month, source_type, now)
        except PlanningError as exc:
            if exc.code != "planning_period_limit":
                raise
            for row in group:
                _apply(row, project_attention(_stored(row), None, now))
            continue
        for row in group:
            fact = facts.get((row.source_id, row.source_date))
            if fact is None:
                if source_type == "recurring":
                    plan = await PlanningRepository(session).plan(user_id, row.source_id)
                    if plan is not None:
                        fact = AttentionFact(
                            "recurring",
                            plan.id,
                            row.source_date,
                            None,
                            plan.name,
                            None,
                            plan.currency,
                            plan.amount,
                            None,
                        )
                if fact is None:
                    await repo.delete_state(row)
                    continue
            _apply(row, project_attention(_stored(row), fact, now))


def next_refresh_at(groups: list[AttentionGroup], now: datetime) -> datetime:
    snoozes = [
        item.snoozed_until
        for group in groups
        for item in group.snoozed
        if item.snoozed_until is not None and item.snoozed_until > now
    ]
    local = now.astimezone(BUSINESS_ZONE)
    boundary = datetime.combine(
        local.date() + timedelta(days=1), time.min, BUSINESS_ZONE
    ).astimezone(UTC)
    return min([boundary, *snoozes])
