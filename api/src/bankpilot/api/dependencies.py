"""
文件职责：定义 API 路由共用的 FastAPI 依赖。

主要内容：
- `get_app_settings`：从应用状态获取配置。
- `get_db_session`：为单次请求提供异步数据库会话。
- `get_current_user`：根据 HttpOnly Cookie 解析已认证用户。

关键边界：原始会话令牌先经 HMAC 哈希再查库，缺失或过期均返回 401。
"""

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.config import Settings
from bankpilot.db.models import UserRecord
from bankpilot.db.repositories import SessionRepository
from bankpilot.security import hash_session_token

SESSION_COOKIE = "bankpilot_session"


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


async def get_current_user(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> UserRecord:
    """根据已哈希且具有过期时间的会话令牌解析当前用户。"""
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token_hash = hash_session_token(session_token, settings.session_secret.get_secret_value())
    user = await SessionRepository(session).resolve_user(token_hash)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return user
