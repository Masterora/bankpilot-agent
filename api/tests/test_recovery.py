"""
文件职责：验证服务重启后的运行状态修复。
主要内容：创建非终态运行，执行修复并断言 UNKNOWN 状态与稳定错误码。
关键边界：中断操作不得被误报为成功或确定失败。
"""

from typing import Any

import pytest

from bankpilot.db.repositories import RunRepository, UserRepository
from bankpilot.domain.contracts import RunStatus


@pytest.mark.asyncio
async def test_interrupted_run_becomes_unknown(app_context: tuple[Any, Any]) -> None:
    _, session_factory = app_context
    async with session_factory() as session, session.begin():
        user = await UserRepository(session).by_email("owner@example.com")
        assert user is not None
        run = await RunRepository(session).create(user_id=user.id, user_message="查询本月账单")
        run_id = run.id

    async with session_factory() as session, session.begin():
        count = await RunRepository(session).reconcile_interrupted()
        assert count == 1

    async with session_factory() as session:
        recovered = await RunRepository(session).get(run_id)
        assert recovered is not None
        assert recovered.status == RunStatus.UNKNOWN.value
        assert recovered.error_code == "OPERATION_STATUS_UNKNOWN"
