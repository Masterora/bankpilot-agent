"""
文件职责：生成预算与助手共享的确定性消费证据。
主要内容：完整月份消费贡献、退款原消费关联、分类汇总、稳定分页及账本和计算版本校验。
关键边界：调用方拥有一致快照事务；超限或版本过期明确失败，不以局部结果冒充完整统计。
"""
import calendar
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
from bankpilot.domain.spending import (
    ComparisonEvidencePage,
    SpendingCategoryComparison,
    SpendingComparison,
    SpendingComparisonCoverage,
    SpendingComparisonPeriod,
    SpendingComparisonScope,
    SpendingCoverage,
    SpendingPage,
    SpendingScope,
    SpendingSummary,
)
from bankpilot.errors import PlanningError
from bankpilot.services.planning_evidence import check_capacity, excluded_ids

# 修改分类、排除、退款归属、贡献或排序语义时必须更新，并验证相关金额与证据口径。
CALCULATION_VERSION = "spending-v1"
COMPARISON_VERSION = "comparison-v1"
PAGE_SIZE = 20


@dataclass
class MonthSpending:
    month: date
    start_date: date
    end_date: date
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
                transaction_count=len(dates),
                earliest_transaction_date=min(dates, default=None),
                latest_transaction_date=max(dates, default=None),
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


async def read_spending_range(
    session: AsyncSession, uid: UUID, month: date, end_date: date
) -> MonthSpending:
    start_date = month.replace(day=1)
    month_end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    if month.day != 1 or end_date < start_date or end_date > month_end:
        raise ValueError("Invalid monthly spending range")
    revision = await UserRepository(session).ledger_revision(uid)
    if revision is None:
        raise PlanningError("user_not_found", 404)
    repo = PlanningRepository(session)
    rows = await repo.transactions(uid, start_date=start_date, end_date=end_date)
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
        month,
        start_date,
        end_date,
        revision,
        datetime.now(UTC),
        evidence,
        totals,
        counts,
        imported_dates,
    )


async def read_spending(session: AsyncSession, uid: UUID, month: date) -> MonthSpending:
    return await read_spending_range(
        session, uid, month, month.replace(day=calendar.monthrange(month.year, month.month)[1])
    )


def comparison_period(
    calculation: MonthSpending, currency: str
) -> SpendingComparisonPeriod:
    entries = [entry for entry in calculation.evidence if entry.currency == currency]
    dates = calculation.imported_dates.get(currency, [])
    gross = sum((entry.contribution for entry in entries if entry.contribution > 0), Decimal())
    refund = -sum((entry.contribution for entry in entries if entry.contribution < 0), Decimal())
    return SpendingComparisonPeriod(
        month=calculation.month,
        start_date=calculation.start_date,
        end_date=calculation.end_date,
        gross_spending=gross,
        refund_offset=refund,
        net_spending=gross - refund,
        contribution_count=len(entries),
        coverage=SpendingComparisonCoverage(
            transaction_count=len(dates),
            earliest_transaction_date=min(dates, default=None),
            latest_transaction_date=max(dates, default=None),
        ),
    )


def category_values(
    calculation: MonthSpending, currency: str, category: TransactionCategory
) -> tuple[Decimal, Decimal, Decimal, int]:
    entries = [
        entry
        for entry in calculation.evidence
        if entry.currency == currency and entry.category == category
    ]
    gross = sum((entry.contribution for entry in entries if entry.contribution > 0), Decimal())
    refund = -sum((entry.contribution for entry in entries if entry.contribution < 0), Decimal())
    return gross, refund, gross - refund, len(entries)


def build_comparison(
    scope: SpendingComparisonScope,
    baseline: MonthSpending,
    target: MonthSpending,
) -> SpendingComparison:
    if baseline.ledger_revision != target.ledger_revision:
        raise PlanningError("assistant_comparison_inconsistent", 409)
    baseline_period = comparison_period(baseline, scope.currency)
    target_period = comparison_period(target, scope.currency)
    categories = {
        entry.category
        for entry in baseline.evidence + target.evidence
        if entry.currency == scope.currency
    }
    rows: list[SpendingCategoryComparison] = []
    for category in categories:
        baseline_gross, baseline_refund, baseline_net, baseline_count = category_values(
            baseline, scope.currency, category
        )
        target_gross, target_refund, target_net, target_count = category_values(
            target, scope.currency, category
        )
        rows.append(
            SpendingCategoryComparison(
                category=category,
                baseline_gross=baseline_gross,
                baseline_refund=baseline_refund,
                baseline_net=baseline_net,
                baseline_count=baseline_count,
                target_gross=target_gross,
                target_refund=target_refund,
                target_net=target_net,
                target_count=target_count,
                delta=target_net - baseline_net,
            )
        )
    rows.sort(key=lambda row: (-abs(row.delta), row.category.value))
    gross_delta = target_period.gross_spending - baseline_period.gross_spending
    refund_delta = target_period.refund_offset - baseline_period.refund_offset
    net_delta = target_period.net_spending - baseline_period.net_spending
    if (
        sum((row.delta for row in rows), Decimal()) != net_delta
        or net_delta != gross_delta - refund_delta
    ):
        raise PlanningError("assistant_comparison_inconsistent", 500)
    baseline_missing = baseline_period.coverage.transaction_count == 0
    target_missing = target_period.coverage.transaction_count == 0
    status = (
        "both_missing"
        if baseline_missing and target_missing
        else "baseline_missing"
        if baseline_missing
        else "target_missing"
        if target_missing
        else "comparable"
    )
    return SpendingComparison(
        scope=scope,
        baseline=baseline_period,
        target=target_period,
        gross_delta=gross_delta,
        refund_delta=refund_delta,
        net_delta=net_delta,
        categories=rows,
        data_status=status,
        ledger_revision=baseline.ledger_revision,
        calculation_version=CALCULATION_VERSION,
        comparison_version=COMPARISON_VERSION,
        calculated_at=max(baseline.calculated_at, target.calculated_at),
    )


def comparison_ends(scope: SpendingComparisonScope, business_date: date) -> tuple[date, date]:
    current_month = business_date.replace(day=1)
    if scope.target_month > current_month:
        raise PlanningError("assistant_comparison_future_month", 422)
    target_end = scope.target_month.replace(
        day=calendar.monthrange(scope.target_month.year, scope.target_month.month)[1]
    )
    baseline_end = scope.baseline_month.replace(
        day=calendar.monthrange(scope.baseline_month.year, scope.baseline_month.month)[1]
    )
    if scope.target_month == current_month:
        target_end = business_date
        baseline_end = scope.baseline_month.replace(
            day=min(
                business_date.day,
                calendar.monthrange(scope.baseline_month.year, scope.baseline_month.month)[1],
            )
        )
    return baseline_end, target_end


async def compare_spending(
    session: AsyncSession,
    uid: UUID,
    scope: SpendingComparisonScope,
    business_date: date,
) -> SpendingComparison:
    baseline_end, target_end = comparison_ends(scope, business_date)
    baseline = await read_spending_range(session, uid, scope.baseline_month, baseline_end)
    target = await read_spending_range(session, uid, scope.target_month, target_end)
    return build_comparison(scope, baseline, target)


async def comparison_evidence_page(
    session: AsyncSession,
    uid: UUID,
    comparison: SpendingComparison,
    side: str,
    category: TransactionCategory,
    page: int,
) -> ComparisonEvidencePage:
    revision = await UserRepository(session).ledger_revision(uid)
    if (
        revision != comparison.ledger_revision
        or comparison.calculation_version != CALCULATION_VERSION
        or comparison.comparison_version != COMPARISON_VERSION
    ):
        raise PlanningError("assistant_evidence_stale", 409)
    if category not in {row.category for row in comparison.categories}:
        raise PlanningError("assistant_comparison_category_invalid", 422)
    period = comparison.baseline if side == "baseline" else comparison.target
    calculation = await read_spending_range(session, uid, period.month, period.end_date)
    # A user's category override does not change the sign of a contribution.
    # Every category included in the frozen comparison must be drillable.
    entries = [
        entry for entry in calculation.evidence
        if entry.category == category and entry.currency == comparison.scope.currency
    ]
    start = (page - 1) * PAGE_SIZE
    return ComparisonEvidencePage(
        comparison=comparison,
        side=side,
        category=category,
        page=page,
        page_size=PAGE_SIZE,
        total=len(entries),
        items=entries[start : start + PAGE_SIZE],
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
