"""Month declarations become stale conservatively on any user ledger revision.

A closed month is a user workflow marker, never an import lock or bank certification.
Raw statement inflows/outflows are kept separate from adjusted spending statistics.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import AccountMonthReviewRecord, TransactionRecord
from bankpilot.db.month_review_repository import MonthReviewRepository
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.month_reviews import AccountMonthReview, MonthReviewInput, MonthReviewTotal
from bankpilot.errors import PlanningError
from bankpilot.services.planning_evidence import check_capacity
from bankpilot.services.planning_reads import planning_today


def checked_review_month(month: date) -> None:
    if month.day != 1 or not 1900 <= month.year <= 9998 or month > planning_today().replace(day=1):
        raise PlanningError("month_review_month", 422)


async def read_month_reviews(
    session: AsyncSession, uid: UUID, month: date
) -> list[AccountMonthReview]:
    checked_review_month(month)
    repo = MonthReviewRepository(session)
    accounts = await repo.accounts(uid)
    records = {r.account_id: r for r in await repo.records(uid, month)}
    rows = await PlanningRepository(session).transactions(uid, month=month)
    check_capacity(len(rows))
    revision = await UserRepository(session).ledger_revision(uid)
    if revision is None:
        raise PlanningError("planning_not_found", 404)
    by_account: dict[UUID, list[TransactionRecord]] = {}
    for row, _, _ in rows:
        by_account.setdefault(row.account_id, []).append(row)
    results = []
    for account in accounts:
        saved = records.get(account.id)
        transactions = by_account.get(account.id, [])
        totals: dict[str, tuple[Decimal, Decimal]] = {}
        for row in transactions:
            incoming, outgoing = totals.get(row.currency, (Decimal("0.00"), Decimal("0.00")))
            totals[row.currency] = (
                incoming + max(row.amount, Decimal(0)),
                outgoing + max(-row.amount, Decimal(0)),
            )
        dates = [r.booking_date for r in transactions]
        saved_status = saved.status if saved else "open"
        status = (
            "stale"
            if saved and saved.status != "open" and saved.ledger_revision != revision
            else saved_status
        )
        results.append(
            AccountMonthReview(
                account_id=account.id,
                account_name=account.name,
                month=month,
                status=status,
                saved_status=saved_status,
                version=saved.version if saved else 0,
                ledger_revision=revision,
                confirmed_at=saved.confirmed_at if saved else None,
                transaction_count=len(transactions),
                first_transaction_date=min(dates) if dates else None,
                last_transaction_date=max(dates) if dates else None,
                totals=[
                    MonthReviewTotal(currency=c, inflow=i, outflow=o)
                    for c, (i, o) in sorted(totals.items())
                ],
                can_close=month < planning_today().replace(day=1) and status == "reviewed",
            )
        )
    return results


async def change_month_review(
    session: AsyncSession, uid: UUID, identity: UUID, payload: MonthReviewInput
) -> AccountMonthReview:
    await UserRepository(session).lock(uid)
    current = next(
        (
            r
            for r in await read_month_reviews(session, uid, payload.month)
            if r.account_id == identity
        ),
        None,
    )
    if current is None:
        raise PlanningError("planning_not_found", 404)
    if (
        current.version != payload.expected_version
        or current.ledger_revision != payload.expected_revision
    ):
        raise PlanningError("planning_stale")
    if payload.action == "close" and not current.can_close:
        raise PlanningError("month_review_close", 422)
    if payload.action == "review" and current.status == "closed":
        raise PlanningError("month_review_reopen")
    record = await session.get(AccountMonthReviewRecord, (identity, payload.month))
    if record is None:
        record = AccountMonthReviewRecord(
            account_id=identity, user_id=uid, month=payload.month, version=0
        )
        session.add(record)
    record.status = {"review": "reviewed", "close": "closed", "reopen": "open"}[payload.action]
    record.ledger_revision = current.ledger_revision
    record.confirmed_at = datetime.now(UTC)
    record.version += 1
    await session.flush()
    return next(
        r for r in await read_month_reviews(session, uid, payload.month) if r.account_id == identity
    )
