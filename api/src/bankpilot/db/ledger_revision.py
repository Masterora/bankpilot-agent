"""
文件职责：维护用户账本修订号。

主要内容：在账本事实变化时对用户修订号执行原子递增。

关键边界：修订号更新与业务写入必须位于同一数据库事务。
"""

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import UserRecord


async def bump_revision(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        update(UserRecord)
        .where(UserRecord.id == user_id)
        .values(ledger_revision=UserRecord.ledger_revision + 1)
        .execution_options(synchronize_session=False)
    )
