"""
文件职责：编排显式预算写入及其待办状态同步。
主要内容：保存、复制上月设置和删除预算；工作区读取由 planning_reads 提供。
关键边界：调用方拥有事务；金额来自确定性消费规则，版本冲突不覆盖已有设置。
"""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.attention_repository import AttentionRepository
from bankpilot.db.models import BudgetRecord
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import (
    BudgetCopyResult,
    BudgetInput,
)
from bankpilot.errors import PlanningError
from bankpilot.services.attention import synchronize_existing_states


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

    if record is not None:
        await session.flush()
        await synchronize_existing_states(
            session, uid, months={key[1]}, source_type="budget", source_id=record.id
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
    await AttentionRepository(session).delete_source(uid, "budget", record.id)
