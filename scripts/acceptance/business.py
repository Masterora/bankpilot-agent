"""R1 接口回归：只在本程序新建的随机数据库运行，结束后删除该数据库。"""

import asyncio
import os
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import asyncpg
import httpx
from sqlalchemy.engine import make_url

from bankpilot.api.app import create_app
from bankpilot.config import Settings
from bankpilot.db.session import create_engine, create_session_factory
from bankpilot.domain.assistant import Answer, ProposeBudget, ReadBudgets, ReadSpending
from bankpilot.domain.spending import SpendingScope
from bankpilot.services.spending import read_spending

ROOT = Path(__file__).resolve().parents[2]
SCOPE = {"month": "2026-09-01", "category": "dining", "currency": "CNY"}
PASSWORD = "Acceptance-only-9835!"


class Decisions:
    def __init__(self, *steps):
        self.steps = iter(steps)
        self.messages = []

    async def decide(self, messages):
        self.messages.append(list(messages))
        return next(self.steps)


def passed(name):
    print("PASS", name, flush=True)


async def request(client, method, path, payload=None, status=200):
    response = await client.request(method, "/api/v1" + path, json=payload)
    assert response.status_code == status, (path, response.status_code, response.text)
    return response.json() if response.content else None


async def seed(client, *, currency="CNY", name="acceptance", rows=None):
    if rows is None:
        rows = [
            "2026-08-20,restaurant original,-50,original",
            "2026-09-01,restaurant A,-500,a",
            "2026-09-02,restaurant B,-250,b",
            "2026-09-03,restaurant C,-150,c",
            "2026-09-04,refund,50,refund",
            "2026-09-05,unconfirmed refund,80,unconfirmed",
        ]
    payload = {
        "file_name": "synthetic.csv",
        "account_name": name,
        "currency": currency,
        "content": "date,merchant,amount,id\n" + "\n".join(rows) + "\n",
        "mapping": {
            "occurred_at": "date",
            "merchant": "merchant",
            "amount": "amount",
            "transaction_id": "id",
        },
        "idempotency_key": str(uuid4()),
    }
    return await request(client, "POST", "/imports", payload, 201)


async def run(factory, url):
    settings = Settings(
        _env_file=None,
        BANKPILOT_DATABASE_URL=url,
        BANKPILOT_SESSION_SECRET="acceptance-" + uuid4().hex,
        BANKPILOT_ENV="test",
        BANKPILOT_SESSION_COOKIE_SECURE=False,
    )
    app = create_app(settings=settings, session_factory=factory)
    app.state.settings = settings
    app.state.session_factory = factory
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://acceptance") as c,
        httpx.AsyncClient(transport=transport, base_url="http://acceptance") as other,
    ):
        user = await request(
            c, "POST", "/auth/register", {"email": "r1@example.com", "password": PASSWORD}, 201
        )
        await request(
            other,
            "POST",
            "/auth/register",
            {"email": "other@example.com", "password": PASSWORD},
            201,
        )
        uid = UUID(user["id"])
        batch = await seed(c)
        ledger = await request(c, "GET", "/transactions?start_date=2026-08-01&end_date=2026-09-30")
        rows = {r["merchant"]: r for r in ledger["items"]}
        relation = {
            "kind": "refund",
            "first_id": rows["restaurant original"]["id"],
            "second_id": rows["refund"]["id"],
            "state": "confirmed",
            "expected_version": 0,
        }
        await request(c, "POST", "/relations", relation, 204)

        async def chat(kind="spending", scope=SCOPE, client=c, followup=False):
            gateway = Decisions(
                ReadBudgets(kind="budgets", arguments={"month": scope["month"]})
                if kind == "budgets"
                else ReadSpending(kind="spending", arguments=scope),
                Answer(kind="answer", text="请查看构成。"),
            )
            app.state.assistant_gateway = gateway
            data = {
                "month": scope["month"],
                "messages": [{"role": "user", "content": "具体哪些？"}],
            }
            if followup:
                data["spending_context"] = scope
            result = await request(client, "POST", "/assistant/chat", data)
            return result, gateway

        async def summary(scope=SCOPE, client=c):
            result, _ = await chat(scope=scope, client=client)
            return result["evidence"][0]["data"]

        async def detail(ref, page=1, client=c, status=200, **overrides):
            params = {
                **ref["scope"],
                "expected_revision": ref["ledger_revision"],
                "expected_calculation_version": ref["calculation_version"],
                "page": page,
                **overrides,
            }
            return await request(
                client,
                "GET",
                "/assistant/spending-evidence?" + str(httpx.QueryParams(params)),
                status=status,
            )

        ref = await summary()
        assert (
            ref["gross_spending"],
            ref["refund_offset"],
            ref["net_spending"],
            ref["contribution_count"],
        ) == ("900.00", "50.00", "850.00", 4)
        assert ref["coverage"]["transaction_count"] == 5
        page = await detail(ref)
        assert sum(Decimal(row["contribution"]) for row in page["items"]) == Decimal("850")
        assert page["items"][0]["purchase"]["booking_date"] == "2026-08-20"
        assert len({row["transaction_id"] for row in page["items"]}) == 4
        passed(
            "independent 900 - 50 = 850; cross-month purchase evidence; unconfirmed refund excluded"
        )

        scope = {**SCOPE, "category": "housing"}
        zero = await summary(scope)
        assert zero["net_spending"] == "0.00" and zero["coverage"]["transaction_count"] == 5
        empty = await summary({**SCOPE, "month": "2026-10-01"})
        assert empty["coverage"]["transaction_count"] == 0
        await seed(c, currency="USD", name="usd", rows=["2026-09-01,restaurant USD,-12,usd"])
        usd = await summary({**SCOPE, "currency": "USD"})
        assert usd["net_spending"] == "12.00"
        ref = await summary()
        await detail(ref, client=other, status=409)
        isolated = await summary(client=other)
        assert (
            isolated["net_spending"] == "0.00"
            and (await detail(isolated, client=other))["items"] == []
        )
        await request(
            other,
            "POST",
            f"/transactions/{rows['restaurant A']['id']}/category",
            {"category": "housing"},
            404,
        )
        passed("no budget required; zero vs absent; currency and user isolation")

        budget = {
            "month": "2026-09-01",
            "category": "housing",
            "currency": "CNY",
            "amount": "100",
            "expected_version": 0,
            "budget_id": None,
        }
        await request(c, "POST", "/budgets", budget, 204)
        reply, _ = await chat("budgets")
        refs = reply["evidence"][0]["data"]["spending_refs"]
        assert next(r for r in refs if r["scope"] == SCOPE)["net_spending"] == "850.00"
        assert any(
            r["scope"]["category"] == "housing" and r["contribution_count"] == 0 for r in refs
        )
        # A budget write does not invalidate spending facts.
        assert (await detail(ref))["summary"]["net_spending"] == "850.00"
        follow, gateway = await chat(followup=True)
        assert any("当前明确选中" in m["content"] for m in gateway.messages[0])
        assert follow["action"] is None
        assert "restaurant A" not in str(gateway.messages)
        passed("shared evidence; structured context; budget edits preserve evidence")

        with patch("bankpilot.services.spending.CALCULATION_VERSION", "spending-v-next"):
            await detail(ref, status=409)
        for invalid in [
            {"month": "2026-09-02"},
            {"category": "income"},
            {"currency": "cny"},
            {"page": 0},
            {"expected_revision": -1},
            {"user_id": str(uid)},
        ]:
            await detail(ref, status=422, **invalid)
        await request(
            c,
            "POST",
            "/assistant/chat",
            {
                "month": "2026-09-01",
                "messages": [{"role": "user", "content": "查账"}],
                "spending_context": {**SCOPE, "amount": "999"},
            },
            422,
        )
        passed("calculation-version invalidation and strict HTTP/context validation")

        # Classification update after a snapshot has started cannot contaminate it.
        async with factory() as snap:
            await snap.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            before = await read_spending(snap, uid, date(2026, 9, 1))
            await request(
                c,
                "POST",
                f"/transactions/{rows['restaurant A']['id']}/category",
                {"category": "housing"},
                204,
            )
            during = await read_spending(snap, uid, date(2026, 9, 1))
            assert before.ledger_revision == during.ledger_revision
            assert during.summary(SpendingScope(**SCOPE)).net_spending == Decimal("850")
        await detail(ref, status=409)
        assert (await summary())["net_spending"] == "350.00"
        await request(
            c,
            "POST",
            f"/transactions/{rows['restaurant A']['id']}/category",
            {"category": "dining"},
            204,
        )
        await request(
            c,
            "POST",
            f"/transactions/{rows['restaurant original']['id']}/category",
            {"category": "shopping"},
            204,
        )
        assert (await summary({**SCOPE, "category": "shopping"}))["net_spending"] == "-50.00"
        passed(
            "snapshot concurrency; stale evidence; original-category correction; negative spending"
        )

        # Stable multi-page evidence with independent total, including equal-date ties.
        await seed(c, name="pages", rows=[f"2026-09-06,coffee page {i},-1,p{i}" for i in range(41)])
        ref = await summary()
        pages = [await detail(ref, n) for n in (1, 2, 3)]
        entries = [row for p in pages for row in p["items"]]
        assert len(entries) == len({r["transaction_id"] for r in entries}) == 44
        assert sum(Decimal(r["contribution"]) for r in entries) == Decimal("941")
        assert entries == sorted(
            entries,
            key=lambda r: (
                -date.fromisoformat(r["booking_date"]).toordinal(),
                UUID(r["transaction_id"]).int,
            ),
        )
        assert (await detail(ref, 999))["items"] == []
        passed("stable pagination, complete totals and beyond-last-page behavior")

        # Confirmed duplicate and transfer removal through real relation APIs.
        duplicate_batch = await seed(
            c, name="duplicate", rows=["2026-09-01,restaurant A,-500,duplicate"]
        )
        wallet = await seed(c, name="wallet", rows=["2026-09-03,transfer,150,in"])
        current = (
            await request(c, "GET", "/transactions?start_date=2026-09-01&end_date=2026-09-30")
        )["items"]
        dup = next(r for r in current if r["import_batch_id"] == duplicate_batch["id"])
        incoming = next(r for r in current if r["import_batch_id"] == wallet["id"])
        for kind, first, second in [
            ("duplicate", rows["restaurant A"]["id"], dup["id"]),
            ("transfer", rows["restaurant C"]["id"], incoming["id"]),
        ]:
            await request(
                c,
                "POST",
                "/relations",
                {
                    "kind": kind,
                    "first_id": first,
                    "second_id": second,
                    "state": "confirmed",
                    "expected_version": 0,
                },
                204,
            )
        assert (await summary())["net_spending"] == "791.00"
        await detail(ref, status=409)
        passed("confirmed duplicate and own-transfer exclusion")

        # Existing proposal contract: no writes before confirm; concurrent confirm applies once.
        app.state.assistant_gateway = Decisions(
            ReadBudgets(kind="budgets", arguments={"month": "2026-09-01"}),
            ProposeBudget(kind="propose_budget", arguments={**SCOPE, "amount": "1000"}),
        )
        proposal = await request(
            c,
            "POST",
            "/assistant/chat",
            {"month": "2026-09-01", "messages": [{"role": "user", "content": "设置餐饮预算1000"}]},
        )
        pid = proposal["action"]["id"]
        await request(other, "POST", "/assistant/confirm", {"id": pid}, 404)
        receipts = await asyncio.gather(
            *(request(c, "POST", "/assistant/confirm", {"id": pid}) for _ in range(2))
        )
        assert (
            receipts[0]["result"] == receipts[1]["result"] and receipts[0]["result"]["version"] == 1
        )
        passed("proposal isolation and concurrent exactly-once budget confirmation")

        async def proposal_id():
            app.state.assistant_gateway = Decisions(
                ReadBudgets(kind="budgets", arguments={"month": "2026-09-01"}),
                ProposeBudget(kind="propose_budget", arguments={**SCOPE, "amount": "1500"}),
            )
            result = await request(
                c,
                "POST",
                "/assistant/chat",
                {
                    "month": "2026-09-01",
                    "messages": [{"role": "user", "content": "改餐饮预算1500"}],
                },
            )
            return result["action"]["id"]

        cancelled = await proposal_id()
        await request(c, "POST", "/assistant/cancel", {"id": cancelled})
        assert (await request(c, "POST", "/assistant/confirm", {"id": cancelled}))[
            "status"
        ] == "cancelled"
        stale_proposal = await proposal_id()
        saved = receipts[0]["result"]
        await request(
            c,
            "POST",
            "/budgets",
            {
                **SCOPE,
                "amount": "1200",
                "expected_version": saved["version"],
                "budget_id": saved["id"],
            },
            204,
        )
        await request(c, "POST", "/assistant/confirm", {"id": stale_proposal}, 409)
        assert (await request(c, "POST", "/assistant/confirm", {"id": pid}))["result"] == saved
        expired = await proposal_id()
        from bankpilot.db.models import AssistantActionRecord

        async with factory() as session:
            action = await session.get(AssistantActionRecord, UUID(expired))
            action.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
            await session.commit()
        await request(c, "POST", "/assistant/confirm", {"id": expired}, 409)
        passed("cancelled/expired/stale proposals rejected; replay retains frozen receipt")

        ref = await summary()
        await request(c, "POST", f"/imports/{batch['id']}/revoke", status=204)
        await detail(ref, status=409)
        assert (await summary())[
            "net_spending"
        ] == "541.00"  # duplicate survives after original batch removal
        passed("import revocation clears relations and invalidates old evidence")

        # Capacity gate uses persisted rows and refuses truncated totals.
        from sqlalchemy import select

        from bankpilot.db.models import AccountRecord, TransactionRecord

        async with factory() as session:
            account = await session.scalar(
                select(AccountRecord).where(AccountRecord.user_id == uid).limit(1)
            )
            for _ in range(10_000):
                session.add(
                    TransactionRecord(
                        account_id=account.id,
                        occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
                        booking_date=date(2026, 11, 1),
                        merchant="coffee capacity",
                        description="",
                        amount=Decimal("-1"),
                        currency="CNY",
                    )
                )
            await session.commit()
        capped = await summary({**SCOPE, "month": "2026-11-01"})
        assert capped["net_spending"] == "10000.00"
        async with factory() as session:
            session.add(
                TransactionRecord(
                    account_id=account.id,
                    occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
                    booking_date=date(2026, 11, 1),
                    merchant="coffee extra",
                    description="",
                    amount=Decimal("-1"),
                    currency="CNY",
                )
            )
            await session.commit()
        await detail(capped, status=422)
        passed("10,000 complete rows accepted; 10,001 refused without partial totals")


async def main(run_checks=run):
    value = os.environ.get("BANKPILOT_ACCEPTANCE_ADMIN_URL")
    if not value:
        raise SystemExit("Set BANKPILOT_ACCEPTANCE_ADMIN_URL to a local/CI admin URL; not run.")
    admin_url = make_url(value)
    if admin_url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Acceptance only permits a local/CI PostgreSQL host.")
    name = "bankpilot_acceptance_" + uuid4().hex
    admin = await asyncpg.connect(
        admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    )
    engine = None
    created = False
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        created = True
        url = admin_url.set(drivername="postgresql+asyncpg", database=name).render_as_string(
            hide_password=False
        )
        env = {**os.environ, "BANKPILOT_DATABASE_URL": url, "BANKPILOT_ENV": "test"}
        for command in (("upgrade", "head"), ("check",)):
            await asyncio.to_thread(
                subprocess.run,
                ["uv", "run", "alembic", *command],
                cwd=ROOT / "api",
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
            )
        engine = create_engine(url)
        await run_checks(create_session_factory(engine), url)
    finally:
        if engine:
            await engine.dispose()
        if created:
            await admin.execute(f'DROP DATABASE "{name}"')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
