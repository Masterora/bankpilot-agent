"""
文件职责：封装银行卡摘要查询。

主要内容：按用户账户关联读取卡片与账户名称。

关键边界：归属过滤在 SQL 中完成，不向调用方返回完整卡号。
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import AccountRecord, CardRecord


class CardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: UUID) -> list[tuple[CardRecord, str]]:
        rows = await self.session.execute(
            select(CardRecord, AccountRecord.name)
            .join(AccountRecord, CardRecord.account_id == AccountRecord.id)
            .where(AccountRecord.user_id == user_id)
            .order_by(CardRecord.created_at, CardRecord.id)
        )
        return list(rows.tuples())
