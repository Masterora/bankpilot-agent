"""
文件职责：验证核查处理、快照历史和来源精度的完整行为。
主要内容：金额歧义拒绝、日期精度降级、结论刷新恢复、跨用户拒绝和撤销后失效。
关键边界：仅使用隔离数据库和人工交易，不访问业务数据或真实模型。
"""

from typing import Any
from uuid import uuid4

import httpx
import pytest

from bankpilot.domain.bill_analysis import analyze_bill
from bankpilot.domain.contracts import TransactionItem
from bankpilot.domain.statement_import import StatementFieldMapping, parse_statement_csv


@pytest.mark.parametrize("amount", ["-12,50", "1,000.00", "1e3", "NaN", "12.345"])
def test_ambiguous_amount_is_rejected(amount: str) -> None:
    result = parse_statement_csv(
        content=f"date;merchant;amount\n2026-09-01;Store;{amount}\n",
        mapping=StatementFieldMapping(occurred_at="date", merchant="merchant", amount="amount"),
        currency="CNY",
    )
    assert result.errors and not result.rows


@pytest.mark.parametrize("timestamp,expected", [("2026-09-01", 0), ("2026-09-01T12:30:00", 1)])
def test_duplicate_rule_requires_real_time_precision(timestamp: str, expected: int) -> None:
    result = parse_statement_csv(
        content=f"date,merchant,amount\n{timestamp},Store,-20\n{timestamp},Store,-20\n",
        mapping=StatementFieldMapping(occurred_at="date", merchant="merchant", amount="amount"),
        currency="CNY",
    )
    items = [
        TransactionItem(
            id=uuid4(),
            booking_date=r.booking_date,
            occurred_at=r.occurred_at,
            amount=r.amount,
            currency=r.currency,
            merchant=r.merchant,
            description=r.description,
            account_name="test",
            time_precision=r.time_precision,
        )
        for r in result.rows
    ]
    assert len(analyze_bill(items).anomalies) == expected


@pytest.mark.asyncio
async def test_review_decisions_history_and_revocation(app_context: tuple[Any, Any]) -> None:
    app, _ = app_context
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def login(owner: bool = True) -> None:
                await client.post(
                    "/api/v1/auth/login",
                    json={
                        "email": "owner@example.com" if owner else "other@example.com",
                        "password": "owner-password" if owner else "other-password",
                    },
                )

            await login()
            payload = {
                "file_name": "review.csv",
                "content": "date,merchant,amount\n2026-01-01,Test,-1500\n",
                "account_name": "Review",
                "currency": "CNY",
                "mapping": {"occurred_at": "date", "merchant": "merchant", "amount": "amount"},
            }
            batch = (await client.post("/api/v1/imports", json=payload)).json()
            period = {"start_date": "2026-01-01", "end_date": "2026-01-02"}
            review = (await client.get("/api/v1/reviews", params=period)).json()["items"][0]
            decision = {**period, "key": review["key"], "state": "normal", "note": "已核对原账单"}
            assert (await client.post("/api/v1/reviews", json=decision)).status_code == 204
            saved = (await client.get("/api/v1/reviews", params=period)).json()["items"][0]
            assert saved["state"] == "normal" and saved["note"] == decision["note"]
            for state in ("follow_up", "pending"):
                assert (
                    await client.post("/api/v1/reviews", json={**decision, "state": state})
                ).status_code == 204
                assert (await client.get("/api/v1/reviews", params=period)).json()["items"][0][
                    "state"
                ] == state
            run = (await client.post("/api/v1/runs", json={"message": "查询本月账单"})).json()
            assert (await client.get("/api/v1/run-history")).json()["items"][0]["id"] == run["id"]
            await login(False)
            assert (await client.get("/api/v1/run-history")).json()["items"] == []
            assert (await client.get("/api/v1/reviews", params=period)).json()["items"] == []
            assert (await client.post("/api/v1/reviews", json=decision)).status_code == 404
            await login()
            assert (await client.post(f"/api/v1/imports/{batch['id']}/revoke")).status_code == 204
            assert (await client.post("/api/v1/reviews", json=decision)).status_code == 404
            assert (await client.get("/api/v1/reviews", params=period)).json()["items"] == []
