"""Shared planning reads: financial facts first, workspace presentation second."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import (
    BudgetRecord,
    RecurringRecord,
    RecurringRevisionRecord,
    TransactionRecord,
)
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import (
    BudgetCoverage,
    BudgetItem,
    BudgetWorkspace,
    RecurringItem,
    RecurringOccurrence,
    RecurringRevision,
    RecurringTransaction,
    RecurringWorkspace,
    UnbudgetedCategory,
    due_in_month,
)
from bankpilot.services.planning_evidence import check_capacity, excluded_ids
from bankpilot.services.spending import MonthSpending, read_spending


@dataclass
class RecurringSource:
    plan: RecurringRecord
    config: RecurringRecord | RecurringRevisionRecord
    history: list[RecurringRevisionRecord]
    occurrences: list[RecurringOccurrence]


@dataclass
class RecurringMonth:
    sources: list[RecurringSource]
    candidates: list[RecurringTransaction]


def budget_items(budgets: list[BudgetRecord], calculation: MonthSpending) -> list[BudgetItem]:
    totals, counts = calculation.totals, calculation.counts
    return [
        BudgetItem(
            id=b.id,
            category=TransactionCategory(b.category),
            currency=b.currency,
            amount=b.amount,
            spent=totals.get((b.category, b.currency), Decimal("0.00")),
            remaining=b.amount - totals.get((b.category, b.currency), Decimal("0.00")),
            overspent=totals.get((b.category, b.currency), Decimal("0.00")) > b.amount,
            version=b.version,
            transaction_count=counts.get((b.category, b.currency), 0),
        )
        for b in budgets
    ]


async def budget_workspace(
    session: AsyncSession,
    uid: UUID,
    month: date,
    *,
    calculation: MonthSpending | None = None,
) -> BudgetWorkspace:
    repo = PlanningRepository(session)
    budgets = await repo.budgets(uid, month)
    calculation = calculation or await read_spending(session, uid, month)
    evidence = calculation.evidence
    totals, counts = calculation.totals, calculation.counts
    imported_dates = calculation.imported_dates
    budgeted = {(b.category, b.currency) for b in budgets}
    return BudgetWorkspace(
        month=month,
        evidence=evidence,
        spending=[
            UnbudgetedCategory(
                category=TransactionCategory(category),
                currency=currency,
                spent=spent,
                transaction_count=counts[(category, currency)],
            )
            for (category, currency), spent in sorted(totals.items())
        ],
        coverage=[
            BudgetCoverage(
                currency=currency,
                transaction_count=len(imported_dates.get(currency, [])),
                latest_transaction_date=max(imported_dates.get(currency, []), default=None),
                limit=sum((b.amount for b in budgets if b.currency == currency), Decimal("0.00")),
                budgeted_spent=sum(
                    (
                        spent
                        for key, spent in totals.items()
                        if key[1] == currency and key in budgeted
                    ),
                    Decimal("0.00"),
                ),
                unbudgeted_spent=sum(
                    (
                        spent
                        for key, spent in totals.items()
                        if key[1] == currency and key not in budgeted
                    ),
                    Decimal("0.00"),
                ),
            )
            for currency in sorted({b.currency for b in budgets} | set(imported_dates))
        ],
        unbudgeted=[
            UnbudgetedCategory(
                category=TransactionCategory(category),
                currency=currency,
                spent=spent,
                transaction_count=counts[(category, currency)],
            )
            for (category, currency), spent in sorted(totals.items())
            if spent > 0 and category != "income" and (category, currency) not in budgeted
        ],
        items=budget_items(budgets, calculation),
    )


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


async def read_recurring_month(
    session: AsyncSession,
    uid: UUID,
    month: date,
    *,
    include_candidates: bool = True,
) -> RecurringMonth:
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
    linked = (
        await repo.linked_ids(uid, {r.id for r, _, _ in period}) if include_candidates else set()
    )
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
        items.append(
            RecurringSource(
                plan, config, history, sorted(occurrences.values(), key=lambda o: o.due_date)
            )
        )
    return RecurringMonth(
        sources=items,
        candidates=[
            recurring_transaction(row, excluded)
            for row, _, _ in period
            if row.amount < 0 and row.id not in excluded and row.id not in linked
        ]
        if include_candidates
        else [],
    )


async def recurring_workspace(session: AsyncSession, uid: UUID, month: date) -> RecurringWorkspace:
    facts = await read_recurring_month(session, uid, month)
    items = []
    for source in facts.sources:
        plan, config, history = source.plan, source.config, source.history
        item = RecurringItem(
            id=plan.id,
            name=plan.name,
            status=cast(Literal["active", "paused", "ended"], plan.status),
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
        item.occurrences = source.occurrences
        items.append(item)
    return RecurringWorkspace(month=month, items=items, candidates=facts.candidates)


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


def planning_today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()
