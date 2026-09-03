"""
文件职责：提供 API 测试共用的隔离应用环境。
主要内容：`app_context` 创建临时 SQLite、两个用户、所属账户和一笔交易，并注入假模型网关。
关键边界：每个测试使用独立临时数据库，不访问真实模型或生产数据。
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bankpilot.api.app import create_app
from bankpilot.config import Settings
from bankpilot.db.base import Base
from bankpilot.db.models import AccountRecord, TransactionRecord
from bankpilot.db.repositories import UserRepository
from bankpilot.db.session import create_session_factory
from bankpilot.security import hash_password
from tests.fakes.model_gateway import FakeModelGateway


@pytest_asyncio.fixture
async def app_context(
    tmp_path: Path,
) -> AsyncIterator[tuple[object, async_sessionmaker[AsyncSession]]]:
    engine: AsyncEngine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    session_factory = create_session_factory(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session, session.begin():
        users = UserRepository(session)
        owner = await users.add(
            email="owner@example.com", password_hash=hash_password("owner-password")
        )
        await users.add(email="other@example.com", password_hash=hash_password("other-password"))
        account = AccountRecord(user_id=owner.id, name="日常账户", currency="CNY")
        session.add(account)
        await session.flush()
        session.add(
            TransactionRecord(
                account_id=account.id,
                occurred_at=datetime.now(UTC),
                merchant="社区超市",
                description="日用品",
                amount=Decimal("-128.50"),
                currency="CNY",
            )
        )

    settings = Settings(
        BANKPILOT_ENV="test",
        BANKPILOT_DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        BANKPILOT_SESSION_SECRET="test-secret-with-more-than-32-characters",
        MODEL_ID="test/fixed-model",
        OPENROUTER_API_KEY="test-only-placeholder",
    )
    app = create_app(settings, session_factory, FakeModelGateway())
    yield app, session_factory
    await engine.dispose()
