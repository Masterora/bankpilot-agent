"""
文件职责：验证 CSV 账单解析、原子导入、账户内去重和用户隔离。

主要内容：覆盖字段映射、重复真实交易、重复文件、失败行报告、零写入和历史归属。
关键边界：测试使用隔离数据库，不读取本地文件，也不访问模型或生产数据。
"""

from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from bankpilot.db.models import AccountRecord, TransactionRecord
from bankpilot.domain.statement_import import StatementFieldMapping, parse_statement_csv


def test_parser_preserves_identical_rows_with_stable_distinct_fingerprints() -> None:
    content = (
        "日期;商户;金额;说明\n"
        "2026/09/01;轨道交通;-6.00;出行\n"
        "2026/09/01;轨道交通;-6.00;出行\n"
    )
    parsed = parse_statement_csv(
        content=content,
        currency="CNY",
        mapping=StatementFieldMapping(
            occurred_at="日期", merchant="商户", amount="金额", description="说明"
        ),
    )

    assert parsed.errors == []
    assert len(parsed.rows) == 2
    assert parsed.rows[0].fingerprint != parsed.rows[1].fingerprint
    assert parsed.rows[0].booking_date.isoformat() == "2026-09-01"
    assert parsed.rows[0].amount.as_tuple().exponent == -2


def test_parser_preserves_booking_date_when_timestamp_has_timezone() -> None:
    content = "date,merchant,amount\n2026-09-01T00:30:00+08:00,Store,-1.00\n"
    parsed = parse_statement_csv(
        content=content,
        currency="CNY",
        mapping=StatementFieldMapping(
            occurred_at="date", merchant="merchant", amount="amount"
        ),
    )

    assert parsed.errors == []
    assert parsed.rows[0].booking_date.isoformat() == "2026-09-01"
    assert parsed.rows[0].occurred_at.isoformat() == "2026-08-31T16:30:00+00:00"


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("date,merchant,amount\n", "NO_DATA_ROWS"),
        ("date,merchant,merchant\n2026-09-01,Store,-10.00\n", "DUPLICATE_HEADER"),
        ("date,merchant,amount\n2026-09-01,Store\n", "INVALID_ROW"),
    ],
)
def test_parser_rejects_ambiguous_csv_structure(content: str, code: str) -> None:
    parsed = parse_statement_csv(
        content=content,
        currency="CNY",
        mapping=StatementFieldMapping(
            occurred_at="date", merchant="merchant", amount="amount"
        ),
    )

    assert parsed.rows == []
    assert parsed.errors[0].code == code


@pytest.mark.asyncio
async def test_csv_import_is_atomic_deduplicated_and_scoped(
    app_context: tuple[Any, Any],
) -> None:
    app, session_factory = app_context
    payload = {
        "file_name": "九月账单.csv",
        "content": (
            "交易日期,交易对方,金额,说明\n"
            "2026-09-01,工资,1000.00,薪资\n"
            "2026/09/02,社区超市,-128.50,日用品\n"
        ),
        "account_name": "导入账户",
        "currency": "cny",
        "mapping": {
            "occurred_at": "交易日期",
            "merchant": "交易对方",
            "amount": "金额",
            "description": "说明",
        },
    }
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )

            first = await client.post("/api/v1/imports", json=payload)
            repeated = await client.post("/api/v1/imports", json=payload)
            history = await client.get("/api/v1/imports")

            assert first.status_code == 201
            assert first.json()["status"] == "COMPLETED"
            assert first.json()["imported_rows"] == 2
            assert first.json()["start_date"] == "2026-09-01"
            assert first.json()["end_date"] == "2026-09-02"
            assert repeated.status_code == 201
            assert repeated.json()["status"] == "COMPLETED_WITH_DUPLICATES"
            assert repeated.json()["imported_rows"] == 0
            assert repeated.json()["duplicate_rows"] == 2
            assert len(history.json()["items"]) == 2

            await client.post("/api/v1/auth/logout")
            await client.post(
                "/api/v1/auth/login",
                json={"email": "other@example.com", "password": "other-password"},
            )
            other_history = await client.get("/api/v1/imports")
            assert other_history.json()["items"] == []

    async with session_factory() as session:
        imported_count = await session.scalar(
            select(func.count(TransactionRecord.id))
            .join(AccountRecord, TransactionRecord.account_id == AccountRecord.id)
            .where(AccountRecord.name == "导入账户")
        )
        assert imported_count == 2


@pytest.mark.asyncio
async def test_invalid_row_rejects_entire_batch_without_creating_account(
    app_context: tuple[Any, Any],
) -> None:
    app, session_factory = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )
            response = await client.post(
                "/api/v1/imports",
                json={
                    "file_name": "invalid.csv",
                    "content": (
                        "date,merchant,amount\n"
                        "2026-09-01,工资,100.00\n"
                        "2026-09-02,商店,invalid\n"
                    ),
                    "account_name": "不应创建",
                    "currency": "CNY",
                    "mapping": {
                        "occurred_at": "date",
                        "merchant": "merchant",
                        "amount": "amount",
                    },
                },
            )

            assert response.status_code == 201
            report = response.json()
            assert report["status"] == "REJECTED"
            assert report["total_rows"] == 2
            assert report["imported_rows"] == 0
            assert report["error_rows"] == 1
            assert report["errors"][0]["row_number"] == 3

    async with session_factory() as session:
        account_count = await session.scalar(
            select(func.count(AccountRecord.id)).where(AccountRecord.name == "不应创建")
        )
        assert account_count == 0


@pytest.mark.asyncio
async def test_import_rejects_non_csv_file_name(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "owner-password"},
            )
            response = await client.post(
                "/api/v1/imports",
                json={
                    "file_name": "statement.xlsx",
                    "content": "date,merchant,amount\n2026-09-01,Store,-10.00\n",
                    "account_name": "日常账户",
                    "currency": "CNY",
                    "mapping": {
                        "occurred_at": "date",
                        "merchant": "merchant",
                        "amount": "amount",
                    },
                },
            )
            assert response.status_code == 422
