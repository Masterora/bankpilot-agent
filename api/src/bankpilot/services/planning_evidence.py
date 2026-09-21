"""
文件职责：提供消费与周期规划共享的证据过滤规则。
主要内容：提取已确认重复副本和本人转账的排除 ID，检查完整证据集合容量。
关键边界：超限明确拒绝，不能以截断集合生成完整统计。
"""
from uuid import UUID

from bankpilot.db.models import TransactionRelationRecord
from bankpilot.errors import PlanningError


def excluded_ids(relations: list[TransactionRelationRecord]) -> set[UUID]:
    return {
        identity
        for r in relations
        for identity in (
            (r.second_id,)
            if r.kind == "duplicate"
            else (r.first_id, r.second_id)
            if r.kind == "transfer"
            else ()
        )
    }


def check_capacity(count: int) -> None:
    if count > 10_000:
        raise PlanningError("planning_period_limit", 422)
