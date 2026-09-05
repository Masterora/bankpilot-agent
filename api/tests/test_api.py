"""
文件职责：验证认证与 Agent 运行 HTTP 主链路。
主要内容：覆盖注册、登录、卡片列表、账单分析、SSE 续传、分类修正、用户隔离与越权拒绝。
关键边界：测试通过 ASGI 内存传输运行，不依赖外部网络。
"""

from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_register_creates_authenticated_user(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            response = await client.post(
                "/api/v1/auth/register",
                json={"email": "NEW.User@example.com", "password": "new-user-password"},
            )

            assert response.status_code == 201
            assert response.json()["email"] == "new.user@example.com"
            assert "bankpilot_session=" in response.headers["set-cookie"]
            assert "HttpOnly" in response.headers["set-cookie"]
            current_user = await client.get("/api/v1/auth/me")
            assert current_user.status_code == 200
            assert current_user.json()["email"] == "new.user@example.com"


@pytest.mark.asyncio
async def test_register_rejects_duplicate_and_weak_password(
    app_context: tuple[Any, Any],
) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            duplicate = await client.post(
                "/api/v1/auth/register",
                json={"email": "OWNER@example.com", "password": "another-password"},
            )
            weak = await client.post(
                "/api/v1/auth/register",
                json={"email": "new@example.com", "password": "too-short"},
            )

            assert duplicate.status_code == 409
            assert duplicate.json()["detail"] == "Email already registered"
            assert weak.status_code == 422


@pytest.mark.asyncio
async def test_authenticated_user_lists_only_own_cards(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )

            response = await client.get("/api/v1/cards")

            assert response.status_code == 200
            payload = response.json()
            assert len(payload["items"]) == 1
            card = payload["items"][0]
            assert UUID(card["id"])
            assert UUID(card["account_id"])
            assert card["account_name"] == "日常账户"
            assert card["display_name"] == "日常卡"
            assert card["last_four"] == "1024"
            assert card["status"] == "ACTIVE"
            assert "9001" not in response.text


@pytest.mark.asyncio
async def test_unauthenticated_card_list_is_rejected(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/cards")
            assert response.status_code == 401


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
            assert payload["result"]["transactions"]["items"][0]["category"] == "groceries"
            assert payload["result"]["analysis"]["currency_summaries"][0]["expense"] == "128.50"
            assert [event["event_type"] for event in payload["events"]] == [
                "run.created",
                "run.planning",
                "tool.started",
                "tool.completed",
                "analysis.completed",
                "run.completed",
            ]


@pytest.mark.asyncio
async def test_sse_reconnect_resumes_after_last_event_id(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )
            created = await client.post("/api/v1/runs", json={"message": "查询本月账单"})

            response = await client.get(
                f"/api/v1/runs/{created.json()['id']}/events",
                headers={"Last-Event-ID": "2"},
            )

            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            event_ids = [
                int(line.removeprefix("id: "))
                for line in response.text.splitlines()
                if line.startswith("id: ")
            ]
            assert event_ids == [3, 4, 5, 6]
            assert len(event_ids) == len(set(event_ids))


@pytest.mark.asyncio
async def test_user_can_correct_category_and_analysis_is_recalculated(
    app_context: tuple[Any, Any],
) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )
            created = await client.post("/api/v1/runs", json={"message": "查询本月账单"})
            run = await client.get(f"/api/v1/runs/{created.json()['id']}")
            transaction_id = run.json()["result"]["transactions"]["items"][0]["id"]

            corrected = await client.post(
                f"/api/v1/runs/{created.json()['id']}/transactions/{transaction_id}/category",
                json={"category": "dining"},
            )

            assert corrected.status_code == 200
            payload = corrected.json()
            transaction = payload["result"]["transactions"]["items"][0]
            assert transaction == run.json()["result"]["transactions"]["items"][0]
            assert payload["result"] == run.json()["result"]
            assert payload["events"][-1]["event_type"] == "transaction.category_corrected"

            next_run = await client.post("/api/v1/runs", json={"message": "再次查询本月账单"})
            persisted = await client.get(f"/api/v1/runs/{next_run.json()['id']}")
            persisted_item = persisted.json()["result"]["transactions"]["items"][0]
            assert persisted_item["category"] == "dining"
            assert persisted_item["category_source"] == "user"


@pytest.mark.asyncio
async def test_category_correction_rejects_invalid_category_and_other_user(
    app_context: tuple[Any, Any],
) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )
            created = await client.post("/api/v1/runs", json={"message": "查询本月账单"})
            run = await client.get(f"/api/v1/runs/{created.json()['id']}")
            transaction_id = run.json()["result"]["transactions"]["items"][0]["id"]
            endpoint = f"/api/v1/runs/{created.json()['id']}/transactions/{transaction_id}/category"

            invalid = await client.post(endpoint, json={"category": "not-a-category"})
            assert invalid.status_code == 422

            await client.post("/api/v1/auth/logout")
            await client.post(
                "/api/v1/auth/login",
                json={"email": "other@example.com", "password": "other-password"},
            )
            forbidden = await client.post(endpoint, json={"category": "dining"})
            assert forbidden.status_code == 404


@pytest.mark.asyncio
async def test_sse_rejects_invalid_last_event_id(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )
            created = await client.post("/api/v1/runs", json={"message": "查询本月账单"})

            response = await client.get(
                f"/api/v1/runs/{created.json()['id']}/events",
                headers={"Last-Event-ID": "invalid"},
            )

            assert response.status_code == 400


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
