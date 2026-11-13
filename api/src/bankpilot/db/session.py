"""集中创建异步 SQLAlchemy 引擎与会话。

本层只管理连接生命周期，不隐式提交业务事务。
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bankpilot.observability import instrument_engine


def create_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url, pool_pre_ping=True, hide_parameters=True)
    instrument_engine(engine)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
