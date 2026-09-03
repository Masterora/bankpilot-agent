"""
文件职责：集中创建异步 SQLAlchemy 引擎与会话。

主要内容：
- `create_engine`：创建带连接预检的异步引擎。
- `create_session_factory`：创建提交后保留对象状态的会话工厂。
- `session_scope`：为依赖注入提供自动关闭的会话上下文。

关键边界：本层只管理连接生命周期，不隐式提交业务事务。
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
