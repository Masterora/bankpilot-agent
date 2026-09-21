"""
文件职责：编排月度预算统计和显式预算写入。
主要内容：基于消费证据构造预算工作区，保存、复制上月设置和删除预算。
关键边界：调用方拥有事务；金额来自确定性消费规则，版本冲突不覆盖已有设置。
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import BudgetRecord
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import (
    BudgetCopyResult,
    BudgetCoverage,
    BudgetInput,
    BudgetItem,
    BudgetWorkspace,
    UnbudgetedCategory,
)
from bankpilot.errors import PlanningError
from bankpilot.services.spending import MonthSpending, read_spending


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
        items=[
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
        ],
    )


async def save_budget(session: AsyncSession, uid: UUID, payload: BudgetInput) -> None:
    await UserRepository(session).lock(uid)
    key = (uid, payload.month.replace(day=1), payload.category.value, payload.currency)
    record = await PlanningRepository(session).budget(*key)
    if payload.expected_version != (record.version if record else 0) or payload.budget_id != (
        record.id if record else None
    ):
        raise PlanningError("planning_stale")
    if record:
        record.amount = payload.amount
        record.version += 1
    else:
        PlanningRepository(session).add(
            BudgetRecord(
                user_id=uid, month=key[1], category=key[2], currency=key[3], amount=payload.amount
            )
        )


async def copy_budgets(session: AsyncSession, uid: UUID, month: date) -> BudgetCopyResult:
    await UserRepository(session).lock(uid)
    repo = PlanningRepository(session)
    previous = (month - timedelta(days=1)).replace(day=1)
    source, target = await repo.budgets(uid, previous), await repo.budgets(uid, month)
    existing = {(r.category, r.currency) for r in target}
    count = 0
    for row in source:
        if (row.category, row.currency) not in existing:
            PlanningRepository(session).add(
                BudgetRecord(
                    user_id=uid,
                    month=month,
                    category=row.category,
                    currency=row.currency,
                    amount=row.amount,
                )
            )
            count += 1
    return BudgetCopyResult(copied=count, source_count=len(source))


async def remove_budget(
    session: AsyncSession,
    uid: UUID,
    month: date,
    category: TransactionCategory,
    currency: str,
    version: int,
    budget_id: UUID,
) -> None:
    await UserRepository(session).lock(uid)
    record = await PlanningRepository(session).budget(uid, month, category.value, currency)
    if record is None:
        raise PlanningError("planning_not_found", 404)
    if record.version != version or record.id != budget_id:
        raise PlanningError("planning_stale")
    await PlanningRepository(session).remove(record)
