"""密码更新与会话撤销在同一事务中完成；调用方提交事务。"""

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.user_repository import SessionRepository, UserRepository
from bankpilot.security import hash_password, verify_password


async def change_password(
    session: AsyncSession,
    *,
    user_id: UUID,
    token_hash: str,
    new_password: str,
) -> None:
    users = UserRepository(session)
    await users.lock(user_id)
    user = await users.by_id(user_id)
    if user is None:
        raise ValueError("session_expired")
    await session.refresh(user)
    sessions = SessionRepository(session)
    if await sessions.resolve_user(token_hash) is None:
        raise ValueError("session_expired")
    if await asyncio.to_thread(verify_password, new_password, user.password_hash):
        raise ValueError("password_unchanged")
    user.password_hash = await asyncio.to_thread(hash_password, new_password)
    await sessions.delete_others(user_id, token_hash)
