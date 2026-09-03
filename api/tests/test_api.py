"""
文件职责：验证认证与 Agent 运行 HTTP 主链路。
主要内容：覆盖登录查账、运行时间线、用户隔离、越权意图拒绝与未认证请求。
关键边界：测试通过 ASGI 内存传输运行，不依赖外部网络。
"""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_login_and_query_own_transactions(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    assert isinstance(app, FastAPI)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )
            assert login.status_code == 200
            assert login.json()["email"] == "owner@example.com"

            created = await client.post("/api/v1/runs", json={"message": "查询本月账单"})
            assert created.status_code == 202
            run_id = created.json()["id"]

            result = await client.get(f"/api/v1/runs/{run_id}")
            assert result.status_code == 200
            payload = result.json()
            assert payload["status"] == "SUCCEEDED"
            assert payload["result"]["transactions"]["items"][0]["merchant"] == "社区超市"
            assert [event["event_type"] for event in payload["events"]] == [
                "run.created",
                "run.planning",
                "tool.started",
                "tool.completed",
                "run.completed",
            ]


@pytest.mark.asyncio
async def test_run_is_scoped_to_authenticated_user(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )
            created = await client.post("/api/v1/runs", json={"message": "查询本月账单"})
            run_id = created.json()["id"]
            await client.post("/api/v1/auth/logout")
            await client.post(
                "/api/v1/auth/login",
                json={"email": "other@example.com", "password": "other-password"},
            )
            response = await client.get(f"/api/v1/runs/{run_id}")
            assert response.status_code == 404


@pytest.mark.asyncio
async def test_unsupported_intent_never_calls_banking_tool(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )
            created = await client.post("/api/v1/runs", json={"message": "给朋友转账 100 元"})
            result = await client.get(f"/api/v1/runs/{created.json()['id']}")
            payload = result.json()
            assert payload["status"] == "FAILED"
            assert payload["error_code"] == "ACTION_NOT_ALLOWED"
            assert all(event["event_type"] != "tool.started" for event in payload["events"])


@pytest.mark.asyncio
async def test_unauthenticated_run_is_rejected(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/runs", json={"message": "查询本月账单"})
            assert response.status_code == 401
