"""
文件职责：封装用户、账本修订号与登录会话持久化。
主要内容：用户查询创建及写锁、修订号读取和原子递增、会话创建解析及单个或其他会话撤销。
关键边界：只保存密码与令牌哈希；不隐式提交，修订号递增与业务写入必须处于同一事务。
"""
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import SessionRecord, UserRecord


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_email(self, email: str, *, lock: bool = False) -> UserRecord | None:
        statement = select(UserRecord).where(UserRecord.email == email.lower())
        if lock:
            statement = statement.with_for_update()
        return cast(UserRecord | None, await self.session.scalar(statement))

    async def by_id(self, user_id: UUID) -> UserRecord | None:
        return await self.session.get(UserRecord, user_id)

    async def lock(self, user_id: UUID) -> None:
        await self.session.scalar(
            select(UserRecord).where(UserRecord.id == user_id).with_for_update()
        )

    async def ledger_revision(self, user_id: UUID) -> int | None:
        revision: int | None = await self.session.scalar(
            select(UserRecord.ledger_revision).where(UserRecord.id == user_id)
        )
        return revision

    async def bump_revision(self, user_id: UUID) -> None:
        """在调用方事务中原子递增修订号，不单独提交。"""
        await self.session.execute(
            update(UserRecord)
            .where(UserRecord.id == user_id)
            .values(ledger_revision=UserRecord.ledger_revision + 1)
            .execution_options(synchronize_session=False)
        )

    async def add(self, *, email: str, password_hash: str) -> UserRecord:
        user = UserRecord(email=email.lower(), password_hash=password_hash)
        self.session.add(user)
        await self.session.flush()
        return user


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, user_id: UUID, token_hash: str, ttl_seconds: int) -> SessionRecord:
        record = SessionRecord(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def resolve_user(self, token_hash: str) -> UserRecord | None:
        statement = (
            select(UserRecord)
            .join(SessionRecord, SessionRecord.user_id == UserRecord.id)
            .where(
                SessionRecord.token_hash == token_hash,
                SessionRecord.expires_at > datetime.now(UTC),
            )
        )
        return cast(UserRecord | None, await self.session.scalar(statement))

    async def delete(self, token_hash: str) -> None:
        await self.session.execute(
            delete(SessionRecord).where(SessionRecord.token_hash == token_hash)
        )

    async def delete_others(self, user_id: UUID, token_hash: str) -> None:
        await self.session.execute(
            delete(SessionRecord).where(
                SessionRecord.user_id == user_id, SessionRecord.token_hash != token_hash
            )
        )
