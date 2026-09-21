"""助手提案持久化：按用户锁定提案，事务由调用方提交。"""

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import (
    AssistantActionRecord,
    AssistantConversationRecord,
    AssistantTurnRecord,
    UserRecord,
)
from bankpilot.errors import PlanningError


class AssistantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def locked_action(self, user_id: UUID, identity: UUID) -> AssistantActionRecord | None:
        record: AssistantActionRecord | None = await self.session.scalar(
            select(AssistantActionRecord)
            .where(
                AssistantActionRecord.id == identity,
                AssistantActionRecord.user_id == user_id,
            )
            .with_for_update()
        )
        return record

    def add(self, action: AssistantActionRecord) -> None:
        self.session.add(action)


# All mutations lock user -> conversation -> turn/action. Model waits hold no locks.
async def lock_owner(session: AsyncSession, uid: UUID) -> None:
    await session.scalar(select(UserRecord).where(UserRecord.id == uid).with_for_update())


async def conversation_record(
    session: AsyncSession, uid: UUID, identity: UUID, *, lock: bool = False
) -> AssistantConversationRecord:
    query = select(AssistantConversationRecord).where(
        AssistantConversationRecord.user_id == uid,
        AssistantConversationRecord.id == identity,
        AssistantConversationRecord.deleted.is_(False),
    )
    row = await session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise PlanningError("assistant_conversation_not_found", 404)
    return row


async def expire_turns(session: AsyncSession, cid: UUID) -> None:
    await session.execute(
        update(AssistantTurnRecord)
        .where(
            AssistantTurnRecord.conversation_id == cid,
            AssistantTurnRecord.status == "processing",
            AssistantTurnRecord.deadline <= func.clock_timestamp(),
        )
        .values(
            status="failed", error_code="assistant_timeout", completed_at=func.clock_timestamp()
        )
    )


async def delete_history(session: AsyncSession, row: AssistantConversationRecord) -> None:
    await session.execute(
        delete(AssistantTurnRecord).where(AssistantTurnRecord.conversation_id == row.id)
    )
    await session.execute(
        update(AssistantActionRecord)
        .where(
            AssistantActionRecord.conversation_id == row.id,
            AssistantActionRecord.status == "pending",
        )
        .values(status="cancelled")
    )
    row.deleted = True
    row.title = None
    row.month = None
    row.scope = None
