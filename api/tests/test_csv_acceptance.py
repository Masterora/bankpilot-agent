"""
文件职责：以可交付 CSV 文件验证完整导入与账本链路。
主要内容：自动识别、账户复用、重叠去重、冲突拒绝、批次撤销与重新导入。
关键边界：固定虚构文件由真实 HTTP 接口读取，测试数据库与模型均隔离。
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "statements"


@pytest.mark.asyncio
async def test_delivered_csv_files_complete_import_lifecycle(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
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

            async def payload(name: str) -> dict[str, Any]:
                content = (FIXTURES / name).read_text(encoding="utf-8")
                detected = await client.post("/api/v1/imports/detect", json={"content": content})
                assert detected.status_code == 200
                return {"file_name": name, "content": content, **detected.json()}

            first_payload = await payload("01-standard.csv")
            assert first_payload["account_name"] == "验收账户"
            preview = (await client.post("/api/v1/imports/preview", json=first_payload)).json()
            assert preview["error_rows"] == preview["duplicate_rows"] == 0
            first = await client.post("/api/v1/imports", json=first_payload)
            assert first.status_code == 201
            assert first.json()["imported_rows"] == 4
            repeated = (await client.post("/api/v1/imports", json=first_payload)).json()
            assert repeated["imported_rows"] == 0
            assert repeated["duplicate_rows"] == 4
            overlap_payload = await payload("02-overlap.csv")
            preview = (await client.post("/api/v1/imports/preview", json=overlap_payload)).json()
            assert preview["duplicate_rows"] == 2
            overlap = (await client.post("/api/v1/imports", json=overlap_payload)).json()
            assert overlap["imported_rows"] == 1
            assert overlap["account_id"] == first.json()["account_id"]
            invalid = await payload("03-invalid.csv")
            preview = (await client.post("/api/v1/imports/preview", json=invalid)).json()
            assert {item["row_number"] for item in preview["errors"]} == {3, 4}
            rejected = (await client.post("/api/v1/imports", json=invalid)).json()
            assert rejected["status"] == "REJECTED"
            assert rejected["imported_rows"] == 0
            conflict = await payload("04-conflict.csv")
            preview = (await client.post("/api/v1/imports/preview", json=conflict)).json()
            assert preview["error_rows"] == 1
            assert (await client.post("/api/v1/imports", json=conflict)).status_code == 409
            query = "/api/v1/transactions?start_date=2026-09-01&end_date=2026-09-05"
            rows = (await client.get(query)).json()["items"]
            imported = [row for row in rows if row["account_name"] == "验收账户"]
            assert len(imported) == 5
            assert sum(Decimal(row["amount"]) for row in imported) == Decimal("9700.00")
            revoke = f"/api/v1/imports/{first.json()['id']}/revoke"
            assert (await client.post(revoke)).status_code == 204
            remaining = (await client.get(query)).json()["items"]
            assert len([row for row in remaining if row["account_name"] == "验收账户"]) == 1
            restored = (await client.post("/api/v1/imports", json=first_payload)).json()
            assert restored["imported_rows"] == 4
