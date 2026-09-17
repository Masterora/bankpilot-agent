"""周期配置与逐期核对；历史配置不可改写，调用方拥有事务。"""

from datetime import date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import (
    RecurringMatchRecord,
    RecurringRecord,
    RecurringRevisionRecord,
    RecurringSkipRecord,
    TransactionRecord,
)
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.planning import (
    RecurringCancelRevisionInput,
    RecurringEditInput,
    RecurringInput,
    RecurringItem,
    RecurringMatchInput,
    RecurringOccurrence,
    RecurringRevision,
    RecurringSkipInput,
    RecurringStatusInput,
    RecurringTransaction,
    RecurringWorkspace,
    due_in_month,
)
from bankpilot.errors import PlanningError
from bankpilot.services.planning_evidence import check_capacity, excluded_ids


def recurring_transaction(row: TransactionRecord, excluded: set[UUID]) -> RecurringTransaction:
    return RecurringTransaction(
        id=row.id,
        account_id=row.account_id,
        booking_date=row.booking_date,
        merchant=row.merchant,
        amount=row.amount,
        currency=row.currency,
        eligible=row.amount < 0 and row.id not in excluded,
    )


async def recurring_workspace(
    session: AsyncSession,
    uid: UUID,
    month: date,
) -> RecurringWorkspace:
    repo = PlanningRepository(session)
    plans = await repo.plans(uid)
    matches = await repo.matches(uid, month)
    revisions = await repo.revisions(uid)
    skips = await repo.skips(uid, month)
    period = await repo.transactions(uid, month=month)
    check_capacity(len(period))
    extra_ids = {m.transaction_id for m in matches} - {r.id for r, _, _ in period}
    extra = await repo.transactions(uid, ids=extra_ids) if extra_ids else []
    check_capacity(len(extra))
    rows = {r.id: r for r, _, _ in period + extra}
    excluded = excluded_ids(await repo.relations(uid, set(rows)))
    linked = await repo.linked_ids(uid, {r.id for r, _, _ in period})
    histories: dict[UUID, list[RecurringRevisionRecord]] = {}
    for revision in revisions:
        histories.setdefault(revision.plan_id, []).append(revision)
    items = []
    for plan in plans:
        history = histories.get(plan.id, [])
        config = effective_config(plan, history, month)
        occurrences = {
            m.due_date: RecurringOccurrence(
                due_date=m.due_date,
                transaction=recurring_transaction(rows[m.transaction_id], excluded),
            )
            for m in matches
            if m.plan_id == plan.id
        }
        for skipped in skips:
            if skipped.plan_id == plan.id:
                occurrences[skipped.due_date] = RecurringOccurrence(
                    due_date=skipped.due_date, transaction=None, skipped=True
                )
        due = due_in_month(config.start_date, config.cadence, month)
        if due and plan.status == "active" and due not in occurrences:
            occurrences[due] = RecurringOccurrence(due_date=due, transaction=None)
        item = RecurringItem(
            id=plan.id,
            name=plan.name,
            status=plan.status,
            version=plan.version,
            next_due_date=next_planned_due(plan, history, month),
            future_revisions=[
                RecurringRevision.model_validate(r)
                for r in history
                if r.effective_month > planning_today().replace(day=1)
            ],
            latest_effective_month=history[-1].effective_month
            if history
            else plan.start_date.replace(day=1),
            **{key: getattr(config, key) for key in CONFIG_FIELDS},
        )
        item.occurrences = sorted(occurrences.values(), key=lambda o: o.due_date)
        items.append(item)
    return RecurringWorkspace(
        month=month,
        items=items,
        candidates=[
            recurring_transaction(row, excluded)
            for row, _, _ in period
            if row.amount < 0 and row.id not in excluded and row.id not in linked
        ],
    )


async def recurring_candidates(
    session: AsyncSession,
    uid: UUID,
    month: date,
) -> list[RecurringTransaction]:
    repo = PlanningRepository(session)
    rows = await repo.transactions(uid, month=month)
    check_capacity(len(rows))
    excluded = excluded_ids(await repo.relations(uid, {row.id for row, _, _ in rows}))
    linked = await repo.linked_ids(uid, {r.id for r, _, _ in rows})
    return [
        recurring_transaction(row, excluded)
        for row, _, _ in rows
        if row.amount < 0 and row.id not in excluded and row.id not in linked
    ]


async def create_recurring(session: AsyncSession, uid: UUID, payload: RecurringInput) -> None:
    await UserRepository(session).lock(uid)
    existing = await PlanningRepository(session).creation_identity(payload.id)
    if existing:
        if existing.user_id == uid and all(
            getattr(existing, key) == value for key, value in payload.model_dump().items()
        ):
            return
        raise PlanningError("planning_conflict")
    account = await PlanningRepository(session).account(uid, payload.account_id)
    if account is None:
        raise PlanningError("planning_not_found", 404)
    if account.currency != payload.currency:
        raise PlanningError("planning_currency", 422)
    PlanningRepository(session).add(RecurringRecord(user_id=uid, **payload.model_dump()))


async def owned_plan(
    session: AsyncSession, uid: UUID, identity: UUID, version: int
) -> RecurringRecord:
    await UserRepository(session).lock(uid)
    plan = await PlanningRepository(session).plan(uid, identity)
    if plan is None:
        raise PlanningError("planning_not_found", 404)
    if plan.version != version:
        raise PlanningError("planning_stale")
    return plan


async def set_recurring_status(
    session: AsyncSession,
    uid: UUID,
    identity: UUID,
    payload: RecurringStatusInput,
) -> None:
    plan = await owned_plan(session, uid, identity, payload.expected_version)
    if plan.status == "ended":
        raise PlanningError("planning_ended")
    plan.status = payload.status
    plan.version += 1


async def match_recurring(
    session: AsyncSession,
    uid: UUID,
    identity: UUID,
    payload: RecurringMatchInput,
) -> None:
    plan = await owned_plan(session, uid, identity, payload.expected_version)
    config = effective_config(
        plan, await PlanningRepository(session).revisions(uid), payload.due_date
    )
    if due_in_month(config.start_date, config.cadence, payload.due_date) != payload.due_date:
        raise PlanningError("planning_due_date", 422)
    if payload.transaction_id is None:
        await PlanningRepository(session).remove_match(identity, payload.due_date)
    else:
        if plan.status != "active":
            raise PlanningError("planning_inactive")
        if await PlanningRepository(session).skip(identity, payload.due_date):
            raise PlanningError("planning_skipped")
        repo = PlanningRepository(session)
        rows = await repo.transactions(uid, ids={payload.transaction_id})
        if not rows:
            raise PlanningError("planning_not_found", 404)
        row = rows[0][0]
        excluded = excluded_ids(await repo.relations(uid, {row.id}))
        if (
            row.account_id != config.account_id
            or row.currency != config.currency
            or row.amount >= 0
            or row.id in excluded
        ):
            raise PlanningError("planning_match_invalid", 422)
        if row.id in await repo.linked_ids(uid, {row.id}):
            raise PlanningError("planning_already_linked")
        if await PlanningRepository(session).match(identity, payload.due_date):
            raise PlanningError("planning_already_linked")
        PlanningRepository(session).add(
            RecurringMatchRecord(plan_id=identity, due_date=payload.due_date, transaction_id=row.id)
        )
    plan.version += 1


CONFIG_FIELDS = ("merchant", "account_id", "currency", "amount", "cadence", "start_date")


def next_planned_due(
    plan: RecurringRecord, history: list[RecurringRevisionRecord], month: date
) -> date | None:
    """在各生效区间寻找下一期，不跨过已安排变更或将暂停项目伪装成待扣款。"""
    if plan.status != "active":
        return None
    configurations: list[RecurringRecord | RecurringRevisionRecord] = [plan, *history]
    for index, config in enumerate(configurations):
        effective = (
            config.effective_month if isinstance(config, RecurringRevisionRecord) else date.min
        )
        boundary = history[index].effective_month if index < len(history) else date.max
        cursor = max(month, effective, config.start_date.replace(day=1))
        if cursor >= boundary:
            continue
        if config.cadence == "yearly":
            year = cursor.year + int(cursor.month > config.start_date.month)
            if year > 9998:
                continue
            cursor = date(year, config.start_date.month, 1)
        due = due_in_month(config.start_date, config.cadence, cursor)
        if due and due < boundary:
            return due
    return None


def effective_config(
    plan: RecurringRecord, revisions: list[RecurringRevisionRecord], month: date
) -> RecurringRecord | RecurringRevisionRecord:
    eligible = [
        r for r in revisions if r.plan_id == plan.id and r.effective_month <= month.replace(day=1)
    ]
    return max(eligible, key=lambda r: r.effective_month) if eligible else plan


async def edit_recurring(
    session: AsyncSession, uid: UUID, identity: UUID, payload: RecurringEditInput
) -> None:
    plan = await owned_plan(session, uid, identity, payload.expected_version)
    if payload.id != identity:
        raise PlanningError("planning_conflict")
    if plan.status == "ended":
        raise PlanningError("planning_ended")
    history = [r for r in await PlanningRepository(session).revisions(uid) if r.plan_id == identity]
    replacement = (
        await PlanningRepository(session).revision(identity, payload.effective_month)
        if payload.replace_revision
        else None
    )
    if payload.replace_revision:
        await ensure_future_revision(session, identity, payload.effective_month)
        if replacement is None:
            raise PlanningError("planning_not_found", 404)
    config = effective_config(plan, history, payload.source_month)
    changed = any(getattr(config, key) != getattr(payload, key) for key in CONFIG_FIELDS)
    if changed or replacement is not None:
        latest = history[-1].effective_month if history else plan.start_date.replace(day=1)
        last_match = await PlanningRepository(session).last_reviewed_date(identity)
        if (
            payload.effective_month < planning_today().replace(day=1)
            or (replacement is None and payload.effective_month <= latest)
            or (last_match and payload.effective_month <= last_match.replace(day=1))
            or payload.start_date.replace(day=1) > payload.effective_month
        ):
            raise PlanningError("planning_effective_month", 422)
        account = await PlanningRepository(session).account(uid, payload.account_id)
        if account is None:
            raise PlanningError("planning_not_found", 404)
        if account.currency != payload.currency:
            raise PlanningError("planning_currency", 422)
        if replacement is not None:
            for key in CONFIG_FIELDS:
                setattr(replacement, key, getattr(payload, key))
        else:
            PlanningRepository(session).add(
                RecurringRevisionRecord(
                    plan_id=identity,
                    effective_month=payload.effective_month,
                    **{key: getattr(payload, key) for key in CONFIG_FIELDS},
                )
            )
    plan.name = payload.name
    plan.version += 1


def planning_today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


async def ensure_future_revision(session: AsyncSession, identity: UUID, month: date) -> None:
    reviewed = await PlanningRepository(session).last_reviewed_date(identity)
    if (
        month.day != 1
        or month <= planning_today().replace(day=1)
        or (reviewed and reviewed >= month)
    ):
        raise PlanningError("planning_revision_locked")


async def cancel_revision(
    session: AsyncSession, uid: UUID, identity: UUID, payload: RecurringCancelRevisionInput
) -> None:
    plan = await owned_plan(session, uid, identity, payload.expected_version)
    if plan.status == "ended":
        raise PlanningError("planning_ended")
    await ensure_future_revision(session, identity, payload.effective_month)
    revision = await PlanningRepository(session).revision(identity, payload.effective_month)
    if revision is None:
        raise PlanningError("planning_not_found", 404)
    await PlanningRepository(session).remove(revision)
    plan.version += 1


async def skip_recurring(
    session: AsyncSession, uid: UUID, identity: UUID, payload: RecurringSkipInput
) -> None:
    plan = await owned_plan(session, uid, identity, payload.expected_version)
    config = effective_config(
        plan, await PlanningRepository(session).revisions(uid), payload.due_date
    )
    if due_in_month(config.start_date, config.cadence, payload.due_date) != payload.due_date:
        raise PlanningError("planning_due_date", 422)
    existing = await PlanningRepository(session).skip(identity, payload.due_date)
    if payload.skipped:
        if plan.status != "active":
            raise PlanningError("planning_inactive")
        if payload.due_date > planning_today():
            raise PlanningError("planning_not_due", 422)
        if await PlanningRepository(session).match(identity, payload.due_date):
            raise PlanningError("planning_already_linked")
        if existing is None:
            PlanningRepository(session).add(
                RecurringSkipRecord(plan_id=identity, due_date=payload.due_date)
            )
    elif existing:
        await PlanningRepository(session).remove(existing)
    plan.version += 1


async def recurring_draft(session: AsyncSession, uid: UUID, transaction_id: UUID) -> RecurringInput:
    repo = PlanningRepository(session)
    rows = await repo.transactions(uid, ids={transaction_id})
    if not rows:
        raise PlanningError("planning_not_found", 404)
    row = rows[0][0]
    if row.amount >= 0 or row.id in excluded_ids(await repo.relations(uid, {row.id})):
        raise PlanningError("planning_match_invalid", 422)
    # 首次日期也是周期锚点；不能用短月截断后的下一期替换原始日期。
    return RecurringInput(
        id=uuid4(),
        name=row.merchant[:100],
        merchant=row.merchant,
        account_id=row.account_id,
        currency=row.currency,
        amount=-row.amount,
        cadence="monthly",
        start_date=row.booking_date,
    )
