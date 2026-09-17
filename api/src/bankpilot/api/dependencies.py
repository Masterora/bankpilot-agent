"""
文件职责：定义 API 路由共用的 FastAPI 依赖。

主要内容：
- `get_app_settings`：从应用状态获取配置。
- `get_db_session`：为单次请求提供异步数据库会话。
- `get_current_user`：根据 HttpOnly Cookie 解析已认证用户。
- `get_snapshot_user` / `get_snapshot_session`：为多次读取共用认证与业务快照。

关键边界：原始会话令牌先经 HMAC 哈希再查库，缺失或过期均返回 401。
"""

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Cookie, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.errors import ApiProblem
from bankpilot.config import Settings
from bankpilot.db.models import UserRecord
from bankpilot.db.user_repository import SessionRepository
from bankpilot.observability import measure
from bankpilot.security import hash_session_token

SESSION_COOKIE = "bankpilot_session"


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


async def get_snapshot_session(request: Request) -> AsyncIterator[AsyncSession]:
    """在认证读取前固定快照；多次查询共用一个连接，关闭会话结束事务。"""
    async with request.app.state.session_factory() as session:
        with measure("connection_ms"):
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        yield session


async def get_current_user(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> UserRecord:
    """根据已哈希且具有过期时间的会话令牌解析当前用户。"""
    if not session_token:
        raise ApiProblem(status.HTTP_401_UNAUTHORIZED, "unauthenticated", "Not authenticated")
    token_hash = hash_session_token(session_token, settings.session_secret.get_secret_value())
    with measure("connection_ms"):
        await session.connection()
    user = await SessionRepository(session).resolve_user(token_hash)
    if user is None:
        raise ApiProblem(status.HTTP_401_UNAUTHORIZED, "session_expired", "Session expired")
    return user


async def get_snapshot_user(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_snapshot_session),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> UserRecord:
    """复用认证规则与快照连接，避免每个只读请求同时占用两条连接。"""
    return await get_current_user(settings, session, session_token)
