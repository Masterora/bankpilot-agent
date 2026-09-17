"""规划共享证据规则：排除已确认副本和转账，完整集合超限时明确拒绝。"""

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
