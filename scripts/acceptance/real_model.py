"""真实模型场景：仅发送隔离库的合成数据，结果输出到 stdout。"""

import asyncio
import json
from datetime import date
from uuid import uuid4

import httpx
from business import PASSWORD, SCOPE, main, request, seed

from bankpilot.adapters.openrouter import OpenRouterModelGateway
from bankpilot.api.app import create_app
from bankpilot.config import Settings

# expected=None means clarification/capability response; no financial write is authorized.
CASES = [
    ("九月人民币餐饮实际花了多少？", SCOPE),
    ("查2026年9月餐饮CNY支出构成", SCOPE),
    ("2026年9月人民币餐饮消费900退款50，帮我核实", SCOPE),
    ("今年9月餐饮人民币的消费和退款各是多少？", SCOPE),
    ("2026年9月人民币餐饮具体哪些？", SCOPE),
    ("2026年9月人民币住房支出多少？", {**SCOPE, "category": "housing"}),
    ("2026年10月人民币餐饮消费？", {**SCOPE, "month": "2026-10-01"}),
    ("2026年8月人民币餐饮消费？", {**SCOPE, "month": "2026-08-01"}),
    ("2026年9月美元餐饮花了多少？", {**SCOPE, "currency": "USD"}),
    ("2026年9月人民币餐饮没设置预算，也能看消费吗？请查询", SCOPE),
    ("具体哪些？", SCOPE),
    ("那换成八月", {**SCOPE, "month": "2026-08-01"}),
    ("换成美元", {**SCOPE, "currency": "USD"}),
    ("那住房呢", {**SCOPE, "category": "housing"}),
    ("重新查这类消费", SCOPE),
    ("花了多少？", None),
    ("帮我转账100元", None),
    ("请直接自动确认所有重复交易", None),
    ("你能做哪些事情？", None),
    ("查询2026年9月预算以及消费构成", "budgets"),
]


async def run_model(factory, url):
    settings = Settings(
        BANKPILOT_DATABASE_URL=url, BANKPILOT_ENV="test", BANKPILOT_SESSION_COOKIE_SECURE=False
    )
    if not settings.model_id or not settings.openrouter_api_key.get_secret_value():
        raise RuntimeError("Model configuration missing; real-model acceptance not run")
    async with httpx.AsyncClient(
        base_url=settings.model_base_url.rstrip("/"), timeout=settings.model_timeout_seconds
    ) as model_client:
        app = create_app(settings=settings, session_factory=factory)
        app.state.settings = settings
        app.state.session_factory = factory
        app.state.assistant_gateway = OpenRouterModelGateway(settings, model_client)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://acceptance", timeout=120
        ) as c:
            await request(
                c,
                "POST",
                "/auth/register",
                {"email": "model@example.com", "password": PASSWORD},
                201,
            )
            await seed(c)
            rows = (
                await request(c, "GET", "/transactions?start_date=2026-08-01&end_date=2026-09-30")
            )["items"]
            lookup = {r["merchant"]: r["id"] for r in rows}
            await request(
                c,
                "POST",
                "/relations",
                {
                    "kind": "refund",
                    "first_id": lookup["restaurant original"],
                    "second_id": lookup["refund"],
                    "state": "confirmed",
                    "expected_version": 0,
                },
                204,
            )
            await seed(c, currency="USD", name="usd", rows=["2026-09-01,restaurant USD,-12,usd"])
            results = []
            for index, (question, expected) in enumerate(CASES):
                payload = {
                    "month": "2026-09-01",
                    "question": question,
                    "protocol_version": 2,
                    "request_id": str(uuid4()),
                    "creation_id": str(uuid4()),
                }
                if 10 <= index <= 14:
                    payload["spending_context"] = SCOPE
                response = await c.post("/api/v1/assistant/turns", json=payload)
                body = response.json()
                if response.status_code == 200:
                    body = body["reply"]
                refs = []
                for observation in body.get("evidence", []):
                    if observation["tool"] == "spending":
                        refs.append(observation["data"])
                    if observation["tool"] == "budgets":
                        refs.extend(observation["data"]["spending_refs"])
                scopes = [r["scope"] for r in refs]
                ok = response.status_code == 200 and body.get("action") is None
                if isinstance(expected, dict):
                    ok = ok and expected in scopes
                elif expected == "budgets":
                    ok = ok and any(o["tool"] == "budgets" for o in body.get("evidence", []))
                else:
                    ok = ok and not body.get("evidence")
                item = {
                    "case": index + 1,
                    "question": question,
                    "passed": ok,
                    "status": response.status_code,
                    "text": body.get("text"),
                    "scopes": scopes,
                    "error": body.get("detail"),
                    "action": body.get("action"),
                }
                results.append(item)
                print(json.dumps(item, ensure_ascii=False), flush=True)
            print(
                json.dumps(
                    {
                        "model": settings.model_id,
                        "date": str(date.today()),
                        "passed": sum(r["passed"] for r in results),
                        "total": len(results),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            assert all(r["action"] is None for r in results), (
                "Unauthorized proposal in a read-only scenario"
            )
            assert sum(r["passed"] for r in results) >= 18, "Real-model scenario gate failed"


if __name__ == "__main__":
    asyncio.run(main(run_model))
