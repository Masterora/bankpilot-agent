"""
文件职责：执行交易搜索的确定性业务与容量验收。
主要内容：验证完整匹配、分页、金额与文本、版本、CSV、防越权、助手上下文及容量和耗时。
关键边界：使用可清理的随机 PostgreSQL 与合成数据，不访问真实模型或生产系统。
"""
import asyncio
import csv
import io
import json
import statistics
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import httpx
from business import PASSWORD, Decisions, main, passed, request, seed
from conversations import Delayed, payload
from sqlalchemy import text

from bankpilot.api.app import create_app
from bankpilot.config import Settings
from bankpilot.db.models import (
    AssistantConversationRecord,
    AssistantTurnRecord,
    TransactionRecord,
    UserRecord,
)
from bankpilot.db.transaction_repository import TransactionRepository
from bankpilot.domain.assistant import Answer, FindArguments, FindTransactions
from bankpilot.errors import PlanningError


async def run(factory, url):
    settings = Settings(
        _env_file=None, BANKPILOT_DATABASE_URL=url, BANKPILOT_SESSION_COOKIE_SECURE=False
    )
    app = create_app(settings=settings, session_factory=factory)
    app.state.settings, app.state.session_factory = settings, factory
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        httpx.AsyncClient(transport=transport, base_url="http://test") as other,
    ):
        user = await request(
            client,
            "POST",
            "/auth/register",
            {"email": "search@test.com", "password": PASSWORD},
            201,
        )
        await request(
            other,
            "POST",
            "/auth/register",
            {"email": "other-search@test.com", "password": PASSWORD},
            201,
        )
        uid = UUID(user["id"])
        batch = await seed(
            client,
            name="Shared",
            rows=[
                "2026-09-01,ＡＣＭＥ Shop,-200,one",
                "2026-09-30,acme shop,-201,two",
                "2026-09-02,100%_literal,-200,three",
                "2026-09-03,zero,0,four",
                "2026-09-04,refund,200,five",
                "2026-08-01,original,-200,six",
            ],
        )
        await seed(
            client,
            name="Shared",
            currency="USD",
            rows=[
                "2026-09-01,acme shop,-200,usd",
            ],
        )
        ledger = await request(
            client, "GET", "/transactions?start_date=2026-08-01&end_date=2026-09-30"
        )
        ids = {row["merchant"]: row["id"] for row in ledger["items"] if row["currency"] == "CNY"}
        accounts = (await request(client, "GET", "/accounts"))["items"]
        cny = next(a for a in accounts if a["currency"] == "CNY")
        base = {"start_date": "2026-09-01", "end_date": "2026-09-30"}

        async def find(filters=None, status=200, **extra):
            return await request(
                client,
                "POST",
                "/transactions/search",
                {"filters": {**base, **(filters or {})}, **extra},
                status,
            )

        def version(page):
            return {
                "expected_revision": page["ledger_revision"],
                "expected_search_version": page["search_version"],
            }

        async def expect(filters, wanted):
            found = await find(filters)
            assert {row["id"] for row in found["items"]} == set(wanted), found
            assert found["total_count"] == len(wanted)
            return found

        await expect(
            {"currency": "CNY", "text": "  ACME\tshop "}, [ids["ＡＣＭＥ Shop"], ids["acme shop"]]
        )
        exact = await expect(
            {"currency": "CNY", "direction": "debit", "min_amount": "200", "max_amount": "200.00"},
            [ids["ＡＣＭＥ Shop"], ids["100%_literal"]],
        )
        assert exact["filters"]["min_amount"] == "200.00"
        await expect({"text": "%_"}, [ids["100%_literal"]])
        await expect({"currency": "CNY", "direction": "credit"}, [ids["refund"]])
        await expect({"currency": "CNY", "min_amount": "0", "max_amount": "0"}, [ids["zero"]])
        await expect(
            {"account_id": cny["id"], "min_amount": "200", "max_amount": "201", "currency": "CNY"},
            [ids["ＡＣＭＥ Shop"], ids["acme shop"], ids["100%_literal"], ids["refund"]],
        )
        await expect({"import_batch_id": batch["id"], "text": "no match"}, [])
        async with factory.begin() as session:
            row = await session.get(TransactionRecord, UUID(ids["zero"]))
            row.description = "ＡＣＭＥ\nSHOP private-note"
        await expect(
            {"text": "acme shop", "currency": "CNY", "text_scope": "merchant_or_note"},
            [ids["ＡＣＭＥ Shop"], ids["acme shop"], ids["zero"]],
        )
        await expect(
            {"text": "acme shop", "currency": "CNY", "text_scope": "merchant"},
            [ids["ＡＣＭＥ Shop"], ids["acme shop"]],
        )
        passed(
            "independent ID sets: normalization, literal wildcards, currency, "
            "signed/absolute amounts, dates, account, batch and note scope"
        )

        for patch in (
            {"min_amount": 200, "currency": "CNY"},
            {"min_amount": "1"},
            {"min_amount": "-1", "currency": "CNY"},
            {"min_amount": "1.001", "currency": "CNY"},
            {"min_amount": "2", "max_amount": "1", "currency": "CNY"},
            {"end_date": "2025-01-01"},
            {"direction": "out"},
            {"text": "x" * 101},
            {"user_id": str(uid)},
        ):
            await find(patch, 422)
        await find(offset=20, status=422)
        await find(expected_revision=exact["ledger_revision"], status=422)
        await find(offset=1, status=422, **version(exact))
        await request(
            other,
            "POST",
            "/transactions/search",
            {"filters": {**base, "account_id": cny["id"]}},
            404,
        )
        await request(
            other,
            "POST",
            "/transactions/search",
            {"filters": {**base, "import_batch_id": batch["id"]}},
            404,
        )
        await request(other, "GET", f"/transactions/{ids['zero']}", status=404)
        await request(
            client, "POST", f"/transactions/{ids['zero']}/category", {"category": "housing"}, 422
        )
        await request(
            client,
            "POST",
            f"/transactions/{ids['zero']}/category",
            {"category": "housing", "expected_revision": exact["ledger_revision"]},
            204,
        )
        await find(status=409, **version(exact))
        await expect({"category": "housing"}, [ids["zero"]])
        await request(
            client,
            "POST",
            f"/transactions/{ids['zero']}/category",
            {"category": "dining", "expected_revision": exact["ledger_revision"]},
            409,
        )
        # Cached authentication object must not hide an intervening committed revision.
        async with factory() as session:
            cached = await session.get(UserRecord, uid)
            stale_revision = cached.ledger_revision
            current = await find()
            await request(
                client,
                "POST",
                f"/transactions/{ids['zero']}/category",
                {"category": "shopping", "expected_revision": current["ledger_revision"]},
                204,
            )
            try:
                await TransactionRepository(session).set_category_override(
                    user_id=uid,
                    transaction_id=UUID(ids["zero"]),
                    category="dining",
                    expected_revision=stale_revision,
                )
            except PlanningError as exc:
                assert exc.code == "search_stale"
            else:
                raise AssertionError("cached auth bypassed lock-time revision")
        passed(
            "strict validation, user isolation, classification and cached-auth "
            "stale write rejection"
        )

        prior = await find()
        await request(
            client,
            "POST",
            "/relations",
            {
                "kind": "refund",
                "first_id": ids["original"],
                "second_id": ids["refund"],
                "state": "confirmed",
                "expected_version": 0,
            },
            204,
        )
        await find(status=409, **version(prior))
        current = await find()
        await request(
            client,
            "POST",
            f"/transactions/{ids['original']}/category",
            {
                "category": "housing",
                "expected_revision": current["ledger_revision"],
            },
            204,
        )
        refund = await expect({"text": "refund", "category": "income"}, [ids["refund"]])
        assert refund["items"][0]["relation_kinds"] == ["refund"]
        await expect({"text": "refund", "category": "housing"}, [])
        # Distinct import and account make confirmed duplicate/transfer fixtures valid.
        await seed(client, name="Shared", rows=["2026-09-02,duplicate,-200,duplicate"])
        await seed(client, name="Transfer", rows=["2026-09-02,transfer in,201,transfer"])
        new_rows = (
            await request(client, "GET", "/transactions?start_date=2026-09-01&end_date=2026-09-30")
        )["items"]
        extra_ids = {r["merchant"]: r["id"] for r in new_rows}
        for kind, first_id, second_id in (
            ("duplicate", ids["100%_literal"], extra_ids["duplicate"]),
            ("transfer", ids["acme shop"], extra_ids["transfer in"]),
        ):
            if kind == "transfer":
                # Keep transfer dates inside the existing three-day window.
                async with factory.begin() as session:
                    row = await session.get(TransactionRecord, UUID(second_id))
                    row.booking_date = date(2026, 9, 30)
                    row.occurred_at = datetime(2026, 9, 30, tzinfo=UTC)
            await request(
                client,
                "POST",
                "/relations",
                {
                    "kind": kind,
                    "first_id": first_id,
                    "second_id": second_id,
                    "state": "confirmed",
                    "expected_version": 0,
                },
                204,
            )
            detail_row = await request(client, "GET", f"/transactions/{second_id}")
            assert kind in detail_row["item"]["relation_kinds"]
        await expect({"text": "duplicate"}, [extra_ids["duplicate"]])
        await expect({"text": "transfer in"}, [extra_ids["transfer in"]])
        app.state.assistant_gateway = ambiguous = Decisions(
            FindTransactions(
                kind="find_transactions", arguments=FindArguments(**base, account_name="Shared")
            )
        )
        clarification = await request(
            client, "POST", "/assistant/turns", payload(question="Shared账户流水")
        )
        assert len(ambiguous.messages) == 1 and clarification["reply"]["evidence"] == []
        assert {a["currency"] for a in clarification["reply"]["account_choices"]} == {"CNY", "USD"}
        passed(
            "refund arrival category, raw confirmed duplicate/transfer visibility; "
            "relation invalidation and account-name ambiguity"
        )

        many = [UUID(int=1000 + n) for n in range(21)]
        async with factory.begin() as session:
            session.add_all(
                [
                    TransactionRecord(
                        id=identity,
                        account_id=UUID(cny["id"]),
                        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
                        booking_date=date(2026, 10, 1),
                        merchant="=same time",
                        time_precision="timestamp",
                        description="private-note",
                        amount=Decimal("-5"),
                        currency="CNY",
                    )
                    for identity in many
                ]
            )
        october = {"start_date": "2026-10-01", "end_date": "2026-10-31"}
        first = await find(october)
        second = await find(october, offset=20, **version(first))
        assert [r["id"] for r in first["items"] + second["items"]] == list(map(str, many))
        assert first["total_count"] == 21 and first["has_more"] and not second["has_more"]
        exports = []
        for page in [first, second]:
            response = await client.post(
                "/api/v1/transactions/search/export",
                json={"filters": page["filters"], **version(page)},
            )
            assert response.status_code == 200
            rows = list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))
            assert len(rows) == 22 and all(row[4] == "'=same time" for row in rows[1:])
            exports.append(response.text)
        assert exports[0] == exports[1]
        projection = await request(
            client,
            "POST",
            "/reviews/projection",
            {
                **october,
                "transaction_ids": [str(many[-1])],
                "expected_revision": first["ledger_revision"],
            },
        )
        duplicate = next(
            i for i in projection["items"] if i["review"]["rule_id"] == "possible_duplicate_v1"
        )
        assert duplicate["evidence_total"] == 2
        assert {r["id"] for r in duplicate["evidence"]} == {str(many[-2]), str(many[-1])}
        last = await request(
            client,
            "POST",
            "/reviews/projection",
            {
                **october,
                "transaction_ids": [str(many[-1])],
                "expected_revision": first["ledger_revision"],
                "evidence_key": duplicate["review"]["key"],
                "evidence_offset": 20,
            },
        )
        assert last["items"][0]["evidence_total"] == 2
        assert last["items"][0]["evidence"] == []
        passed(
            "21 equal-time rows: stable pages, full CSV from either page, "
            "formula escaping and cross-page review evidence"
        )

        app.state.assistant_gateway = gateway = Decisions(
            FindTransactions(kind="find_transactions", arguments=FindArguments(**october)),
            Answer(kind="answer", text="Found transactions"),
        )
        turn = await request(client, "POST", "/assistant/turns", payload(question="查十月流水"))
        assert len(turn["reply"]["evidence"][0]["data"]["items"]) == 20
        assert "=same time" not in str(gateway.messages) and "private-note" not in str(
            gateway.messages
        )
        cid = turn["conversation_id"]
        context_path = f"/assistant/conversations/{cid}/search-context"
        saved = await request(
            client,
            "PUT",
            context_path,
            {"filters": first["filters"], "expected_context_version": 1},
        )
        assert saved["context_version"] == 2
        await request(
            client, "PUT", context_path, {"filters": None, "expected_context_version": 1}, 409
        )
        await request(
            other, "PUT", context_path, {"filters": None, "expected_context_version": 2}, 404
        )
        slow = Delayed()
        app.state.assistant_gateway = slow
        task = asyncio.create_task(
            request(
                client,
                "POST",
                "/assistant/turns",
                payload(
                    creation_id=None,
                    conversation_id=cid,
                    expected_context_version=2,
                    question="继续查",
                ),
            )
        )
        await slow.entered.wait()
        await request(
            client,
            "PUT",
            context_path,
            {"filters": {**base, "text": "next query"}, "expected_context_version": 3},
        )
        slow.release.set()
        finished = await task
        detail = await request(client, "GET", f"/assistant/conversations/{cid}")
        assert detail["conversation"]["search_context"]["text"] == "next query"
        async with factory() as session:
            row = await session.get(AssistantTurnRecord, UUID(finished["id"]))
            assert row.search_context["start_date"] == "2026-10-01"
        await request(client, "POST", f"/assistant/conversations/{cid}/delete")
        async with factory() as session:
            tomb = await session.get(AssistantConversationRecord, UUID(cid))
            assert tomb.search_context is None
        passed(
            "assistant row privacy, bounded history, context conflicts, accepted "
            "snapshot, late completion and delete cleanup"
        )

        capacity = [UUID(int=100000 + n) for n in range(10001)]
        async with factory.begin() as session:
            session.add_all(
                [
                    TransactionRecord(
                        id=identity,
                        account_id=UUID(cny["id"]),
                        occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
                        booking_date=date(2026, 11, 1),
                        merchant=f"capacity {n}",
                        description="",
                        amount=Decimal("-1"),
                        currency="CNY",
                    )
                    for n, identity in enumerate(capacity[:1000])
                ]
            )
        november = {"start_date": "2026-11-01", "end_date": "2026-11-30"}

        async def benchmark(count):
            cold_start = time.perf_counter()
            sample = await find(november)
            cold = (time.perf_counter() - cold_start) * 1000
            for concurrency in (1, 5):
                durations = []

                async def once(offset, durations=durations):
                    start = time.perf_counter()
                    await find(november, offset=offset, **version(sample))
                    durations.append((time.perf_counter() - start) * 1000)

                for _ in range(4):
                    await asyncio.gather(*(once(0 if i % 2 else 20) for i in range(concurrency)))
                print(
                    json.dumps(
                        {
                            "rows": count,
                            "concurrency": concurrency,
                            "cold_ms": round(cold, 2),
                            "p50_ms": round(statistics.median(durations), 2),
                            "p95_ms": round(sorted(durations)[int((len(durations) - 1) * 0.95)], 2),
                            "page_bytes": len(json.dumps(sample).encode()),
                        }
                    ),
                    flush=True,
                )
            return sample

        await benchmark(1000)
        async with factory.begin() as session:
            session.add_all(
                [
                    TransactionRecord(
                        id=identity,
                        account_id=UUID(cny["id"]),
                        occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
                        booking_date=date(2026, 11, 1),
                        merchant=f"capacity {n}",
                        description="",
                        amount=Decimal("-1"),
                        currency="CNY",
                    )
                    for n, identity in enumerate(capacity[1000:10000])
                ]
            )
        capped = await benchmark(10000)
        assert capped["total_count"] == 10000
        async with factory.begin() as session:
            session.add(
                TransactionRecord(
                    id=capacity[-1],
                    account_id=UUID(cny["id"]),
                    occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
                    booking_date=date(2026, 11, 1),
                    merchant="extra",
                    description="",
                    amount=Decimal("-1"),
                    currency="CNY",
                )
            )
            plan = await session.execute(
                text(
                    "EXPLAIN SELECT * FROM transactions WHERE account_id=:id AND "
                    "booking_date BETWEEN '2026-11-01' AND '2026-11-30' "
                    "ORDER BY booking_date DESC, occurred_at DESC, id LIMIT 10001"
                ),
                {"id": UUID(cny["id"])},
            )
            print("SQL plan:", "\n".join(plan.scalars()), flush=True)
        error = await find(november, status=422)
        assert error["detail"]["code"] == "search_capacity_exceeded"
        failed_export = await client.post(
            "/api/v1/transactions/search/export",
            json={"filters": capped["filters"], **version(capped)},
        )
        assert (
            failed_export.status_code == 422 and "csv" not in failed_export.headers["content-type"]
        )
        await request(client, "POST", f"/imports/{batch['id']}/revoke", status=204)
        await request(client, "GET", f"/transactions/{ids['zero']}", status=404)
        await find(october, status=409, **version(first))
        failed_export = await client.post(
            "/api/v1/transactions/search/export",
            json={"filters": first["filters"], **version(first)},
        )
        assert (
            failed_export.status_code == 409 and "csv" not in failed_export.headers["content-type"]
        )
        await request(
            client,
            "POST",
            "/reviews",
            {
                **october,
                "key": duplicate["review"]["key"],
                "state": "normal",
                "expected_revision": first["ledger_revision"],
            },
            409,
        )
        passed(
            "1000/10000 measurements; 10001 capacity fails without partial CSV; "
            "revocation invalidates details, pages, exports and review writes"
        )


if __name__ == "__main__":
    asyncio.run(main(run))
