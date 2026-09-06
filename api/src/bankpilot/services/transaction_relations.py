"""
文件职责：编排交易关系读取、证据装配、并发确认与统计计算。
主要内容：用户级写锁、版本比较、候选分页、跨期间证据和互斥退款校验。
关键边界：所有交易和关系按用户读取；确认前重查事实，撤销导入通过外键清理关联。
"""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import (
    AccountRecord,
    TransactionRecord,
    TransactionRelationRecord,
    UserRecord,
)
from bankpilot.domain.transaction_relations import (
    Relation,
    RelationTransaction,
    adjusted_summary,
    suggest_relations,
    validate_conflicts,
    validate_pair,
)


class RelationError(Exception):
    """携带稳定错误代码与 HTTP 状态，页面负责本地化。"""

    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status


def to_transaction(row: TransactionRecord) -> RelationTransaction:
    return RelationTransaction(
        id=row.id,
        account_id=row.account_id,
        booking_date=row.booking_date,
        occurred_at=row.occurred_at,
        time_precision=row.time_precision,
        merchant=row.merchant,
        description=row.description,
        amount=row.amount,
        currency=row.currency,
        import_batch_id=row.import_batch_id,
    )


def to_relation(row: TransactionRelationRecord) -> Relation:
    return Relation(row.kind, row.first_id, row.second_id)


async def lock_user(session: AsyncSession, user_id: UUID) -> None:
    """确认、撤销和源交易撤销使用相同锁顺序，串行校验重叠关系。"""
    await session.scalar(select(UserRecord).where(UserRecord.id == user_id).with_for_update())


async def save_relation(
    session: AsyncSession,
    *,
    user_id: UUID,
    kind: str,
    first_id: UUID,
    second_id: UUID,
    state: str,
    expected_version: int,
) -> None:
    """客户端仅提交意图与读到的版本；金额、互斥及累计退款全部重新计算。"""
    await lock_user(session, user_id)
    rows = list(
        await session.scalars(
            select(TransactionRecord)
            .join(AccountRecord)
            .where(
                AccountRecord.user_id == user_id,
                TransactionRecord.id.in_([first_id, second_id]),
            )
        )
    )
    if len(rows) != 2:
        raise RelationError("evidence_unavailable", 404)
    transactions = {r.id: to_transaction(r) for r in rows}
    # 重复关系允许用户选择保留哪条，但反向记录共用一份版本与状态。
    pair: ColumnElement[bool] = (TransactionRelationRecord.first_id == first_id) & (
        TransactionRelationRecord.second_id == second_id
    )
    if kind == "duplicate":
        pair = or_(
            pair,
            (TransactionRelationRecord.first_id == second_id)
            & (TransactionRelationRecord.second_id == first_id),
        )
    record = await session.scalar(
        select(TransactionRelationRecord).where(
            TransactionRelationRecord.user_id == user_id,
            TransactionRelationRecord.kind == kind,
            pair,
        )
    )
    if expected_version != (record.version if record else 0):
        raise RelationError("stale_version")
    if state == "revoked" and (record is None or record.state != "confirmed"):
        raise RelationError("not_confirmed")
    if record and record.state == "confirmed" and state != "revoked":
        raise RelationError("revoke_first")
    try:
        validate_pair(kind, transactions[first_id], transactions[second_id])
        if state == "confirmed":
            active = list(
                await session.scalars(
                    select(TransactionRelationRecord).where(
                        TransactionRelationRecord.user_id == user_id,
                        TransactionRelationRecord.state == "confirmed",
                        or_(
                            TransactionRelationRecord.first_id.in_([first_id, second_id]),
                            TransactionRelationRecord.second_id.in_([first_id, second_id]),
                        ),
                    )
                )
            )
            related_ids = {r.second_id for r in active} - transactions.keys()
            if related_ids:
                extra = await session.scalars(
                    select(TransactionRecord)
                    .join(AccountRecord)
                    .where(
                        AccountRecord.user_id == user_id,
                        TransactionRecord.id.in_(related_ids),
                    )
                )
                transactions.update({r.id: to_transaction(r) for r in extra})
            validate_conflicts(
                Relation(kind, first_id, second_id), [to_relation(r) for r in active], transactions
            )
    except ValueError as exc:
        raise RelationError(str(exc), 422) from exc
    if record is None:
        record = TransactionRelationRecord(user_id=user_id, kind=kind, version=0)
        session.add(record)
    record.first_id, record.second_id, record.state = first_id, second_id, state
    record.version += 1
    await session.commit()


async def relation_workspace(
    session: AsyncSession,
    user_id: UUID,
    start: date,
    end: date,
) -> dict[str, Any]:
    """扩展九十天查找跨期证据；超过工作区上限拒绝而不返回不完整统计。"""
    await lock_user(session, user_id)
    low = date.fromordinal(max(date.min.toordinal(), start.toordinal() - 90))
    high = min(end, date.max - timedelta(days=90)) + timedelta(days=90)
    rows = list(
        (
            await session.execute(
                select(TransactionRecord, AccountRecord.name)
                .join(AccountRecord)
                .where(
                    AccountRecord.user_id == user_id,
                    TransactionRecord.booking_date.between(low, high),
                )
                .order_by(TransactionRecord.booking_date, TransactionRecord.id)
                .limit(10_001)
            )
        ).all()
    )
    if len(rows) > 10_000:
        raise RelationError("narrow_period", 422)
    transactions = {row.id: to_transaction(row) for row, _ in rows}
    period_ids = {t.id for t in transactions.values() if start <= t.booking_date <= end}
    if not period_ids:
        return {"items": [], "truncated": False, "summaries": [], "transactions": []}
    records = list(
        await session.scalars(
            select(TransactionRelationRecord)
            .where(
                TransactionRelationRecord.user_id == user_id,
                or_(
                    TransactionRelationRecord.first_id.in_(transactions),
                    TransactionRelationRecord.second_id.in_(transactions),
                ),
            )
            .order_by(TransactionRelationRecord.updated_at.desc(), TransactionRelationRecord.id)
        )
    )
    active = [to_relation(r) for r in records if r.state == "confirmed"]
    # 累计退款校验可能引用窗口外的另一笔退款，补齐金额事实但不纳入候选或期间流水。
    extra_ids = {r.second_id for r in active} - transactions.keys()
    if extra_ids:
        extra = await session.scalars(
            select(TransactionRecord)
            .join(AccountRecord)
            .where(
                AccountRecord.user_id == user_id,
                TransactionRecord.id.in_(extra_ids),
            )
        )
        transactions.update({r.id: to_transaction(r) for r in extra})
    records = [r for r in records if period_ids.intersection((r.first_id, r.second_id))]
    # 对所有扩展窗口候选先按期间筛选，再限流，避免无关月份耗尽候选名额。
    suggestions, truncated = suggest_relations(
        [to_transaction(row) for row, _ in rows],
        limit=1000,
        period_ids=period_ids,
    )

    def pair_key(kind: str, a: UUID, b: UUID) -> tuple[str, str, str]:
        first, second = sorted((str(a), str(b)))
        return kind, first, second

    saved = {pair_key(r.kind, r.first_id, r.second_id) for r in records}
    candidates = [
        r
        for r in suggestions
        if period_ids.intersection((r.first_id, r.second_id))
        and pair_key(r.kind, r.first_id, r.second_id) not in saved
    ]
    # 已参与确认关系的记录不再展示冲突候选，部分退款允许原消费继续匹配。
    available: list[Relation] = []
    for candidate in candidates:
        try:
            validate_conflicts(candidate, active, transactions)
        except ValueError:
            continue
        available.append(candidate)
    items: list[dict[str, Any]] = [
        {
            "id": r.id,
            "kind": r.kind,
            "first_id": r.first_id,
            "second_id": r.second_id,
            "state": r.state,
            "version": r.version,
            "updated_at": r.updated_at,
        }
        for r in records
    ]
    items.extend(
        {
            "id": None,
            "kind": r.kind,
            "first_id": r.first_id,
            "second_id": r.second_id,
            "state": "pending",
            "version": 0,
            "updated_at": None,
        }
        for r in available[:200]
    )
    evidence_ids = period_ids | {i[key] for i in items for key in ("first_id", "second_id")}
    return {
        "items": items,
        "truncated": truncated or len(available) > 200,
        "summaries": adjusted_summary(list(transactions.values()), active, start, end),
        "transactions": [
            {
                "id": row.id,
                "account_id": row.account_id,
                "account_name": name,
                "booking_date": row.booking_date,
                "occurred_at": row.occurred_at,
                "time_precision": row.time_precision,
                "merchant": row.merchant,
                "description": row.description,
                "amount": str(row.amount),
                "currency": row.currency,
                "import_batch_id": row.import_batch_id,
                "source_row_number": row.source_row_number,
            }
            for row, name in rows
            if row.id in evidence_ids
        ],
    }
