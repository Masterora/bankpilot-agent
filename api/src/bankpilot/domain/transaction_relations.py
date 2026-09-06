"""
文件职责：定义交易关系的确定性校验、候选规则及按币种调整统计。
主要内容：重复记录保留方向、本人转账配对、部分退款累计校验、期间统计。
关键边界：候选不代表事实；仅 confirmed 关系影响统计，退款按到账日冲减流出。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

RelationKind = Literal["duplicate", "transfer", "refund"]
RelationState = Literal["confirmed", "rejected", "revoked"]


@dataclass(frozen=True)
class RelationTransaction:
    id: UUID
    account_id: UUID
    booking_date: date
    occurred_at: datetime
    time_precision: str
    merchant: str
    description: str
    amount: Decimal
    currency: str
    import_batch_id: UUID | None


@dataclass(frozen=True)
class Relation:
    kind: str
    first_id: UUID
    second_id: UUID


class AdjustedSummary(BaseModel):
    currency: str
    raw_inflow: Decimal = Decimal("0.00")
    raw_outflow: Decimal = Decimal("0.00")
    adjusted_inflow: Decimal = Decimal("0.00")
    adjusted_outflow: Decimal = Decimal("0.00")
    adjusted_net: Decimal = Decimal("0.00")
    duplicate_excluded: int = 0
    transfer_excluded: int = 0
    refund_amount: Decimal = Decimal("0.00")


def validate_pair(kind: str, first: RelationTransaction, second: RelationTransaction) -> None:
    """校验事实约束；重复的第一条由用户指定保留，转账和退款第一条必须为流出。"""
    if first.id == second.id or first.currency != second.currency:
        raise ValueError("distinct_same_currency")
    days = (second.booking_date - first.booking_date).days
    if kind == "duplicate":
        if (
            first.amount != second.amount
            or first.amount == 0
            or abs(days) > 1
            or first.import_batch_id == second.import_batch_id
        ):
            raise ValueError("duplicate_mismatch")
    elif kind == "transfer":
        if (
            first.amount >= 0
            or second.amount != -first.amount
            or first.account_id == second.account_id
            or abs(days) > 3
        ):
            raise ValueError("transfer_mismatch")
    elif kind == "refund":
        if not (first.amount < 0 < second.amount <= -first.amount and 0 <= days <= 90):
            raise ValueError("refund_mismatch")
        if (
            first.time_precision == second.time_precision == "timestamp"
            and second.occurred_at < first.occurred_at
        ):
            raise ValueError("refund_mismatch")
    else:
        raise ValueError("unknown_kind")


def validate_conflicts(
    candidate: Relation,
    confirmed: list[Relation],
    transactions: dict[UUID, RelationTransaction],
) -> None:
    """重复记录只排除副本；保留记录可继续关联转账或退款，拒绝链式重复抵销。"""
    ids = {candidate.first_id, candidate.second_id}
    refund_total = transactions[candidate.second_id].amount
    for relation in confirmed:
        if not ids.intersection((relation.first_id, relation.second_id)):
            continue
        if candidate.kind == "duplicate":
            if candidate.second_id in (relation.first_id, relation.second_id) or (
                relation.kind == "duplicate" and candidate.first_id == relation.second_id
            ):
                raise ValueError("transaction_already_linked")
            continue
        if relation.kind == "duplicate":
            if relation.second_id in ids:
                raise ValueError("transaction_already_linked")
            continue
        if (
            candidate.kind == relation.kind == "refund"
            and candidate.first_id == relation.first_id
            and candidate.second_id != relation.second_id
        ):
            refund_total += transactions[relation.second_id].amount
        else:
            raise ValueError("transaction_already_linked")
    if candidate.kind == "refund" and refund_total > -transactions[candidate.first_id].amount:
        raise ValueError("refund_exceeds_purchase")


def suggest_relations(
    transactions: list[RelationTransaction],
    *,
    limit: int = 200,
    period_ids: set[UUID] | None = None,
) -> tuple[list[Relation], bool]:
    """按商户、币种索引查找候选；工作量设上限，达到上限明确返回未穷尽标记。"""
    merchants: dict[tuple[str, str], list[RelationTransaction]] = defaultdict(list)
    amounts: dict[tuple[str, Decimal], list[RelationTransaction]] = defaultdict(list)
    result: list[Relation] = []
    inspected = 0
    for row in sorted(transactions, key=lambda t: (t.booking_date, t.occurred_at, str(t.id))):
        merchant = " ".join(row.merchant.casefold().split())
        prior = {t.id: t for t in merchants[(row.currency, merchant)]}
        prior.update({t.id: t for t in amounts[(row.currency, -row.amount)]})
        for other in prior.values():
            inspected += 1
            if inspected > 50_000:
                return result, True
            if period_ids is not None and not period_ids.intersection((row.id, other.id)):
                continue
            kinds: list[str] = []
            same_merchant = bool(merchant) and merchant == " ".join(
                other.merchant.casefold().split()
            )
            if same_merchant and row.amount == other.amount:
                kinds.append("duplicate")
            searchable = (
                f"{row.merchant} {row.description} {other.merchant} {other.description}".casefold()
            )
            if any(word in searchable for word in ("转账", "还款", "transfer", "repayment")):
                kinds.append("transfer")
            if same_merchant and any(word in searchable for word in ("退款", "退货", "refund")):
                kinds.append("refund")
            for kind in kinds:
                first, second = (
                    (other, row) if kind == "duplicate" or other.amount < 0 else (row, other)
                )
                try:
                    validate_pair(kind, first, second)
                except ValueError:
                    continue
                result.append(Relation(kind, first.id, second.id))
                if len(result) >= limit:
                    return result, True
        merchants[(row.currency, merchant)].append(row)
        amounts[(row.currency, row.amount)].append(row)
    return result, False


def adjusted_summary(
    transactions: list[RelationTransaction],
    confirmed: list[Relation],
    start: date,
    end: date,
) -> list[AdjustedSummary]:
    """按发生日计算现金流调整；跨期另一端不移入期间，退款可使当期流出为负。"""
    excluded: dict[UUID, str] = {}
    refunds: set[UUID] = set()
    for relation in confirmed:
        if relation.kind == "duplicate":
            excluded[relation.second_id] = "duplicate"
        elif relation.kind == "transfer":
            excluded[relation.first_id] = excluded[relation.second_id] = "transfer"
        elif relation.kind == "refund":
            refunds.add(relation.second_id)
    totals: dict[str, AdjustedSummary] = {}
    for row in transactions:
        if not start <= row.booking_date <= end:
            continue
        value = totals.setdefault(row.currency, AdjustedSummary(currency=row.currency))
        value.raw_inflow += max(row.amount, Decimal(0))
        value.raw_outflow += max(-row.amount, Decimal(0))
        if row.id in excluded:
            if excluded[row.id] == "duplicate":
                value.duplicate_excluded += 1
            else:
                value.transfer_excluded += 1
        elif row.id in refunds:
            value.refund_amount += row.amount
            value.adjusted_outflow -= row.amount
        elif row.amount > 0:
            value.adjusted_inflow += row.amount
        else:
            value.adjusted_outflow -= row.amount
        value.adjusted_net = value.adjusted_inflow - value.adjusted_outflow
    return [totals[key] for key in sorted(totals)]
