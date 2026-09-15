"""
文件职责：封装账户列表与名称写入。
主要内容：按用户读取账户、锁定并重命名、更新账本修订号。
关键边界：先锁用户再锁账户；不隐式提交，不改变账户身份与历史快照。
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.ledger_revision import bump_revision
from bankpilot.db.models import AccountRecord
from bankpilot.db.user_repository import UserRepository


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: UUID) -> list[AccountRecord]:
        return list(
            await self.session.scalars(
                select(AccountRecord)
                .where(AccountRecord.user_id == user_id)
                .order_by(AccountRecord.created_at, AccountRecord.id)
            )
        )

    async def rename(self, user_id: UUID, account_id: UUID, name: str) -> bool:
        await UserRepository(self.session).lock(user_id)
        account = await self.session.scalar(
            select(AccountRecord)
            .where(AccountRecord.id == account_id, AccountRecord.user_id == user_id)
            .with_for_update()
        )
        if account is None:
            return False
        if account.name != name:
            account.name = name
            await bump_revision(self.session, user_id)
        return True
