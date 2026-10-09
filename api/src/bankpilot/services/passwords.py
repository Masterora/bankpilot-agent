"""
文件职责：编排当前用户密码修改与其他会话撤销。
主要内容：锁定用户、验证旧密码、生成新哈希并撤销其他登录会话。
关键边界：密码更新和会话撤销处于同一事务，由调用方提交；不记录明文密码。
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.user_repository import SessionRepository, UserRepository
from bankpilot.security import hash_password_async, verify_password_async


async def change_password(
    session: AsyncSession,
    *,
    user_id: UUID,
    token_hash: str,
    current_password: str,
    new_password: str,
) -> None:
    users = UserRepository(session)
    await users.lock(user_id)
    user = await users.by_id(user_id)
    if user is None:
        raise ValueError("session_expired")
    await session.refresh(user)
    sessions = SessionRepository(session)
    owner = await sessions.resolve_user(token_hash)
    if owner is None or owner.id != user_id:
        raise ValueError("session_expired")
    if not await verify_password_async(current_password, user.password_hash):
        raise ValueError("current_password_invalid")
    if await verify_password_async(new_password, user.password_hash):
        raise ValueError("password_unchanged")
    user.password_hash = await hash_password_async(new_password)
    await sessions.delete_others(user_id, token_hash)
