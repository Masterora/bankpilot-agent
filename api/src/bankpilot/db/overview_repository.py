"""
文件职责：提供财务总览的数据库只读投影。
主要内容：按币种计算原始与调整收支，并读取最近五笔期间流水。
关键边界：调用方提供一致快照事务；仅使用已确认关系，不提交事务或发现候选。
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import (
    AccountRecord,
    TransactionRecord,
    TransactionRelationRecord,
)
from bankpilot.domain.contracts import OverviewSnapshot
from bankpilot.errors import RelationError

CENT = Decimal("0.01")


def money(value: Decimal | None) -> Decimal:
    """统一 API 金额精度，数据库全零聚合也保持两位小数。"""
    return (value or Decimal("0")).quantize(CENT)


async def read_overview(
    session: AsyncSession,
    user_id: UUID,
    start: date,
    end: date,
) -> OverviewSnapshot:
    """在数据库中完成统计，只把按币种结果和五条明细返回应用层。"""
    period_filter = (
        AccountRecord.user_id == user_id,
        TransactionRecord.booking_date.between(start, end),
    )
    transaction_count = await session.scalar(
        select(func.count())
        .select_from(TransactionRecord)
        .join(AccountRecord)
        .where(*period_filter)
    )
    if transaction_count and transaction_count > 10_000:
        raise RelationError("narrow_period", 422)
    if not transaction_count:
        return OverviewSnapshot(summaries=[], recent_transactions=[])

    confirmed = (
        TransactionRelationRecord.user_id == user_id,
        TransactionRelationRecord.state == "confirmed",
    )
    relation_flags = union_all(
        select(
            TransactionRelationRecord.second_id.label("transaction_id"),
            literal(1).label("duplicate"),
            literal(0).label("transfer"),
            literal(0).label("refund"),
        ).where(*confirmed, TransactionRelationRecord.kind == "duplicate"),
        select(
            TransactionRelationRecord.first_id.label("transaction_id"),
            literal(0).label("duplicate"),
            literal(1).label("transfer"),
            literal(0).label("refund"),
        ).where(*confirmed, TransactionRelationRecord.kind == "transfer"),
        select(
            TransactionRelationRecord.second_id.label("transaction_id"),
            literal(0).label("duplicate"),
            literal(1).label("transfer"),
            literal(0).label("refund"),
        ).where(*confirmed, TransactionRelationRecord.kind == "transfer"),
        select(
            TransactionRelationRecord.second_id.label("transaction_id"),
            literal(0).label("duplicate"),
            literal(0).label("transfer"),
            literal(1).label("refund"),
        ).where(*confirmed, TransactionRelationRecord.kind == "refund"),
    ).subquery()
    flags = (
        select(
            relation_flags.c.transaction_id,
            func.max(relation_flags.c.duplicate).label("duplicate"),
            func.max(relation_flags.c.transfer).label("transfer"),
            func.max(relation_flags.c.refund).label("refund"),
        )
        .where(
            relation_flags.c.transaction_id.in_(
                select(TransactionRecord.id).join(AccountRecord).where(*period_filter)
            )
        )
        .group_by(relation_flags.c.transaction_id)
        .subquery()
    )
    duplicate = func.coalesce(flags.c.duplicate, 0) == 1
    transfer = func.coalesce(flags.c.transfer, 0) == 1
    refund = func.coalesce(flags.c.refund, 0) == 1
    amount = TransactionRecord.amount
    rows = (
        (
            await session.execute(
                select(
                    TransactionRecord.currency,
                    func.sum(case((amount > 0, amount), else_=0)).label("raw_inflow"),
                    func.sum(case((amount < 0, -amount), else_=0)).label("raw_outflow"),
                    func.sum(
                        case((or_(duplicate, transfer, refund), 0), (amount > 0, amount), else_=0)
                    ).label("adjusted_inflow"),
                    func.sum(
                        case(
                            (or_(duplicate, transfer), 0),
                            (refund, -amount),
                            (amount < 0, -amount),
                            else_=0,
                        )
                    ).label("adjusted_outflow"),
                    func.sum(case((duplicate, 1), else_=0)).label("duplicate_excluded"),
                    func.sum(case((transfer, 1), else_=0)).label("transfer_excluded"),
                    func.sum(case((refund, amount), else_=0)).label("refund_amount"),
                )
                .join(AccountRecord)
                .outerjoin(flags, flags.c.transaction_id == TransactionRecord.id)
                .where(*period_filter)
                .group_by(TransactionRecord.currency)
                .order_by(TransactionRecord.currency)
            )
        )
        .mappings()
        .all()
    )
    summaries = []
    for row in rows:
        adjusted_inflow = money(row["adjusted_inflow"])
        adjusted_outflow = money(row["adjusted_outflow"])
        summaries.append(
            {
                "currency": row["currency"],
                "raw_inflow": money(row["raw_inflow"]),
                "raw_outflow": money(row["raw_outflow"]),
                "adjusted_inflow": adjusted_inflow,
                "adjusted_outflow": adjusted_outflow,
                "adjusted_net": adjusted_inflow - adjusted_outflow,
                "duplicate_excluded": row["duplicate_excluded"],
                "transfer_excluded": row["transfer_excluded"],
                "refund_amount": money(row["refund_amount"]),
            }
        )

    recent = (
        await session.execute(
            select(TransactionRecord, AccountRecord.name)
            .join(AccountRecord)
            .where(*period_filter)
            .order_by(TransactionRecord.occurred_at.desc(), TransactionRecord.id.desc())
            .limit(5)
        )
    ).all()
    return OverviewSnapshot.model_validate(
        {
            "summaries": summaries,
            "recent_transactions": [
                {
                    "id": row.id,
                    "account_id": row.account_id,
                    "account_name": name,
                    "booking_date": row.booking_date,
                    "occurred_at": row.occurred_at,
                    "time_precision": row.time_precision,
                    "merchant": row.merchant,
                    "description": row.description,
                    "amount": row.amount,
                    "currency": row.currency,
                    "import_batch_id": row.import_batch_id,
                    "source_row_number": row.source_row_number,
                }
                for row, name in recent
            ],
        }
    )
