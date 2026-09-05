"""
文件职责：验证普通用户账本与导入确认链路。
主要内容：预览零写入、独立查询、分类保存、跨用户撤销拒绝和重复撤销。
关键边界：使用隔离数据库与替身模型，不读取真实账单或访问外部服务。
"""

from typing import Any

import httpx
import pytest


@pytest.mark.asyncio
async def test_preview_ledger_and_revoke_are_user_scoped(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    payload = {
        "file_name": "statement.csv",
        "content": "date,merchant,amount\n2026-01-01,Store,-5\n",
        "account_name": "Personal",
        "currency": "CNY",
        "mapping": {"occurred_at": "date", "merchant": "merchant", "amount": "amount"},
    }
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "owner-password",
                },
            )
            preview = await client.post("/api/v1/imports/preview", json=payload)
            assert preview.status_code == 200
            assert preview.json()["total_rows"] == 1
            assert (await client.get("/api/v1/imports")).json()["items"] == []
            batch = (await client.post("/api/v1/imports", json=payload)).json()
            query = "/api/v1/transactions?start_date=2026-01-01&end_date=2026-01-01"
            rows = (await client.get(query)).json()["items"]
            assert len(rows) == 1
            corrected = await client.post(
                f"/api/v1/transactions/{rows[0]['id']}/category", json={"category": "dining"}
            )
            assert corrected.status_code == 204
            assert (await client.get(query)).json()["items"][0]["category"] == "dining"
            await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "other@example.com",
                    "password": "other-password",
                },
            )
            assert (await client.get(query)).json()["items"] == []
            path = f"/api/v1/imports/{batch['id']}/revoke"
            assert (await client.post(path)).status_code == 404
            await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "owner-password",
                },
            )
            assert (await client.post(path)).status_code == 204
            assert (await client.post(path)).status_code == 204
            assert (await client.get(query)).json()["items"] == []
            assert (await client.get("/api/v1/imports")).json()["items"][0]["status"] == "REVOKED"
