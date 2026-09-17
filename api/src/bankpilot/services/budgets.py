"""月度预算统计与写入；调用方拥有事务，版本冲突不覆盖输入。"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import BudgetRecord
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.bill_analysis import classify_transaction
from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import (
    BudgetCopyResult,
    BudgetCoverage,
    BudgetEvidence,
    BudgetInput,
    BudgetItem,
    BudgetPurchase,
    BudgetWorkspace,
    UnbudgetedCategory,
)
from bankpilot.errors import PlanningError
from bankpilot.services.planning_evidence import check_capacity, excluded_ids


async def budget_workspace(session: AsyncSession, uid: UUID, month: date) -> BudgetWorkspace:
    repo = PlanningRepository(session)
    budgets = await repo.budgets(uid, month)
    rows = await repo.transactions(uid, month=month)
    check_capacity(len(rows))
    relations = await repo.relations(uid, {row.id for row, _, _ in rows})
    excluded = excluded_ids(relations)
    refunds = {r.second_id: r.first_id for r in relations if r.kind == "refund"}
    purchases = await repo.transactions(uid, ids=set(refunds.values())) if refunds else []
    check_capacity(len(purchases))
    all_rows = {row.id: (row, override) for row, _, override in rows + purchases}
    account_names = {row.id: name for row, name, _ in rows + purchases}
    evidence = []
    for row, account_name, override in rows:
        if row.id in excluded or (row.amount >= 0 and row.id not in refunds):
            continue
        purchase_id = refunds.get(row.id)
        source, category_override = all_rows[purchase_id] if purchase_id else (row, override)
        category = classify_transaction(
            merchant=source.merchant,
            description=source.description,
            amount=source.amount,
            override=TransactionCategory(category_override) if category_override else None,
        ).category
        evidence.append(
            BudgetEvidence(
                transaction_id=row.id,
                booking_date=row.booking_date,
                merchant=row.merchant,
                account_name=account_name,
                category=category,
                currency=row.currency,
                amount=row.amount,
                contribution=-row.amount,
                purchase=BudgetPurchase(
                    id=source.id,
                    booking_date=source.booking_date,
                    merchant=source.merchant,
                    account_name=account_names[source.id],
                    amount=source.amount,
                )
                if purchase_id
                else None,
            )
        )
    totals: dict[tuple[str, str], Decimal] = {}
    counts: dict[tuple[str, str], int] = {}
    for entry in evidence:
        key = (entry.category, entry.currency)
        totals[key] = totals.get(key, Decimal("0.00")) + entry.contribution
        counts[key] = counts.get(key, 0) + 1
    imported_dates: dict[str, list[date]] = {}
    for row, _, _ in rows:
        imported_dates.setdefault(row.currency, []).append(row.booking_date)
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
