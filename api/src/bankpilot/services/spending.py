"""共享消费贡献：完整月份统计、稳定分页及账本/计算版本校验。调用方拥有事务。"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.bill_analysis import classify_transaction
from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import BudgetEvidence, BudgetPurchase
from bankpilot.domain.spending import SpendingCoverage, SpendingPage, SpendingScope, SpendingSummary
from bankpilot.errors import PlanningError
from bankpilot.services.planning_evidence import check_capacity, excluded_ids

# 修改分类、排除、退款归属、贡献或排序语义时必须更新，并执行 verify-business。
CALCULATION_VERSION = "spending-v1"
PAGE_SIZE = 20


@dataclass
class MonthSpending:
    month: date
    ledger_revision: int
    calculated_at: datetime
    evidence: list[BudgetEvidence]
    totals: dict[tuple[str, str], Decimal]
    counts: dict[tuple[str, str], int]
    imported_dates: dict[str, list[date]]

    def summary(self, scope: SpendingScope) -> SpendingSummary:
        entries = self.entries(scope)
        dates = self.imported_dates.get(scope.currency, [])
        gross = sum((e.contribution for e in entries if e.contribution > 0), Decimal("0.00"))
        refund = -sum((e.contribution for e in entries if e.contribution < 0), Decimal("0.00"))
        return SpendingSummary(
            scope=scope,
            ledger_revision=self.ledger_revision,
            calculation_version=CALCULATION_VERSION,
            calculated_at=self.calculated_at,
            gross_spending=gross,
            refund_offset=refund,
            net_spending=gross - refund,
            contribution_count=len(entries),
            coverage=SpendingCoverage(
                transaction_count=len(dates), latest_transaction_date=max(dates, default=None)
            ),
        )

    def entries(self, scope: SpendingScope) -> list[BudgetEvidence]:
        if scope.month != self.month:
            raise ValueError("Scope does not belong to this month")
        return [
            e
            for e in self.evidence
            if e.category == scope.category and e.currency == scope.currency
        ]


async def read_spending(session: AsyncSession, uid: UUID, month: date) -> MonthSpending:
    revision = await UserRepository(session).ledger_revision(uid)
    if revision is None:
        raise PlanningError("user_not_found", 404)
    repo = PlanningRepository(session)
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
    evidence.sort(key=lambda entry: (-entry.booking_date.toordinal(), entry.transaction_id.int))
    return MonthSpending(
        month, revision, datetime.now(UTC), evidence, totals, counts, imported_dates
    )


async def spending_page(
    session: AsyncSession,
    uid: UUID,
    scope: SpendingScope,
    expected_revision: int,
    expected_calculation_version: str,
    page: int,
) -> SpendingPage:
    revision = await UserRepository(session).ledger_revision(uid)
    if revision != expected_revision or expected_calculation_version != CALCULATION_VERSION:
        raise PlanningError("assistant_evidence_stale", 409)
    result = await read_spending(session, uid, scope.month)
    entries = result.entries(scope)
    start = (page - 1) * PAGE_SIZE
    return SpendingPage(
        summary=result.summary(scope),
        page=page,
        page_size=PAGE_SIZE,
        total=len(entries),
        items=entries[start : start + PAGE_SIZE],
    )
