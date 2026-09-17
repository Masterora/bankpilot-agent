"""助手提案持久化：按用户锁定提案，事务由调用方提交。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import AssistantActionRecord


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
