"""
文件职责：验收助手持久会话与轮次恢复。
主要内容：并发受理、同请求恢复、归属隔离、迟到写回、删除和恢复库任务核对。
关键边界：只使用随机临时 PostgreSQL 与模拟模型，不访问生产或真实模型。
"""
import asyncio
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from business import PASSWORD, SCOPE, Decisions, main, passed, request
from sqlalchemy import func, select, update

from bankpilot.api.app import create_app
from bankpilot.config import Settings
from bankpilot.db.models import (
    AssistantActionRecord,
    AssistantConversationRecord,
    AssistantTurnRecord,
)
from bankpilot.domain.assistant import Answer, ProposeBudget, ReadBudgets
from bankpilot.services.conversations import ConversationService
from bankpilot.services.restore_validation import database_evidence, prepare_restored_tasks


class Delayed:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def decide(self, messages):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return Answer(kind="answer", text="Saved answer")


def payload(**extra):
    return {
        "protocol_version": 3,
        "expected_context_version": 0,
        "creation_id": str(uuid4()),
        "request_id": str(uuid4()),
        "question": "本月餐饮预算",
        "month": "2026-09-01",
        **extra,
    }


async def run(factory, url):
    settings = Settings(
        _env_file=None, BANKPILOT_DATABASE_URL=url, BANKPILOT_SESSION_COOKIE_SECURE=False
    )
    app = create_app(settings=settings, session_factory=factory)
    app.state.settings, app.state.session_factory = settings, factory
    service = ConversationService(factory, settings)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        httpx.AsyncClient(transport=transport, base_url="http://test") as other,
    ):
        await request(
            client, "POST", "/auth/register", {"email": "r2@test.com", "password": PASSWORD}, 201
        )
        await request(
            other, "POST", "/auth/register", {"email": "other@test.com", "password": PASSWORD}, 201
        )
        response = await client.post("/api/v1/assistant/chat", json={"messages": []})
        assert response.status_code == 409
        data = payload()
        slow = Delayed()
        app.state.assistant_gateway = slow
        task = asyncio.create_task(request(client, "POST", "/assistant/turns", data))
        await slow.entered.wait()
        lookup = f"/assistant/turns/{data['request_id']}?creation_id={data['creation_id']}"
        accepted = await request(client, "GET", lookup)
        assert accepted["status"] == "processing"
        cid = accepted["conversation_id"]
        duplicate = await request(client, "POST", "/assistant/turns", data)
        assert duplicate["id"] == accepted["id"] and slow.calls == 1
        await request(client, "POST", "/assistant/turns", {**data, "question": "changed"}, 409)
        await request(other, "GET", f"/assistant/conversations/{cid}", status=404)
        await request(other, "GET", lookup, status=404)
        await request(
            client, "POST", "/assistant/turns", payload(creation_id=None, conversation_id=cid), 409
        )
        slow.release.set()
        completed = await task
        assert completed["status"] == "completed" and completed["reply"]["text"] == "Saved answer"
        assert (await request(client, "POST", "/assistant/turns", data))["id"] == completed["id"]
        assert slow.calls == 1
        passed("accepted-before-model; duplicate/conflict; user isolation; response-loss replay")

        gateway = Decisions(Answer(kind="answer", text="Continuation"))
        app.state.assistant_gateway = gateway
        await request(
            client,
            "POST",
            "/assistant/turns",
            payload(
                creation_id=None,
                conversation_id=cid,
                spending_context=SCOPE,
                expected_context_version=1,
            ),
        )
        assert any(m["content"] == "Saved answer" for m in gateway.messages[0])
        detail = await request(client, "GET", f"/assistant/conversations/{cid}")
        assert len(detail["turns"]) == 2 and detail["conversation"]["scope"] == SCOPE
        await request(
            client,
            "POST",
            f"/assistant/conversations/{cid}/scope",
            {"month": SCOPE["month"], "spending_context": None, "expected_context_version": 2},
        )
        passed("server-owned context and selected-scope persistence")

        for mode in ("timeout", "delete", "cancel"):
            slow = Delayed()
            app.state.assistant_gateway = slow
            data2 = payload()
            task = asyncio.create_task(client.post("/api/v1/assistant/turns", json=data2))
            await slow.entered.wait()
            turn = await request(
                client,
                "GET",
                f"/assistant/turns/{data2['request_id']}?creation_id={data2['creation_id']}",
            )
            target = turn["conversation_id"]
            if mode == "timeout":
                async with factory.begin() as session:
                    await session.execute(
                        update(AssistantTurnRecord)
                        .where(AssistantTurnRecord.id == UUID(turn["id"]))
                        .values(deadline=func.clock_timestamp() - timedelta(seconds=1))
                    )
                await asyncio.gather(service.reconcile(), service.reconcile())
            elif mode == "delete":
                await request(client, "POST", f"/assistant/conversations/{target}/delete")
            else:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            slow.release.set()
            if mode != "cancel":
                assert (await task).status_code in (404, 409)
            if mode == "delete":
                await request(client, "POST", "/assistant/turns", data2, 410)
                async with factory() as session:
                    tombstone = await session.get(AssistantConversationRecord, UUID(target))
                    assert tombstone.title is None and tombstone.scope is None
            else:
                detail = await request(client, "GET", f"/assistant/conversations/{target}")
                assert detail["turns"][0]["status"] == "failed"
                app.state.assistant_gateway = Decisions(Answer(kind="answer", text="Retry"))
                await request(
                    client,
                    "POST",
                    "/assistant/turns",
                    payload(
                        creation_id=None,
                        conversation_id=target,
                        retry_of=turn["id"],
                        expected_context_version=1,
                    ),
                )
        passed("multi-instance deadline; late completion; delete tombstone; explicit retry")

        async def proposal():
            app.state.assistant_gateway = Decisions(
                ReadBudgets(kind="budgets", arguments={"month": SCOPE["month"]}),
                ProposeBudget(kind="propose_budget", arguments={**SCOPE, "amount": "1000"}),
            )
            return await request(client, "POST", "/assistant/turns", payload())

        proposed = await proposal()
        action_id = proposed["reply"]["action"]["id"]
        assert proposed["reply"]["action"]["can_confirm"]
        saved = await request(client, "POST", "/assistant/confirm", {"id": action_id})
        assert saved["status"] == "applied"
        await request(
            client, "POST", f"/assistant/conversations/{proposed['conversation_id']}/delete"
        )
        assert (await request(client, "POST", "/assistant/confirm", {"id": action_id}))[
            "result"
        ] == saved["result"]
        pending = await proposal()
        await request(
            client, "POST", f"/assistant/conversations/{pending['conversation_id']}/delete"
        )
        assert (
            await request(
                client, "POST", "/assistant/confirm", {"id": pending["reply"]["action"]["id"]}
            )
        )["status"] == "cancelled"
        expired = await proposal()
        async with factory.begin() as session:
            await session.execute(
                update(AssistantActionRecord)
                .where(AssistantActionRecord.id == UUID(expired["reply"]["action"]["id"]))
                .values(expires_at=func.clock_timestamp() - timedelta(seconds=1))
            )
        detail = await request(
            client, "GET", f"/assistant/conversations/{expired['conversation_id']}"
        )
        assert detail["turns"][0]["reply"]["action"]["effective_status"] == "expired"
        passed("effective proposal expiry; deleted pending action; applied receipt retained")

        # Crash after model returns but before commit: no orphan proposal may survive.
        async with factory() as session:
            count = await session.scalar(select(func.count()).select_from(AssistantActionRecord))
        with patch(
            "bankpilot.services.conversations.turn_view",
            side_effect=RuntimeError("injected completion failure"),
        ):
            app.state.assistant_gateway = Decisions(
                ReadBudgets(kind="budgets", arguments={"month": SCOPE["month"]}),
                ProposeBudget(kind="propose_budget", arguments={**SCOPE, "amount": "1200"}),
            )
            try:
                await request(client, "POST", "/assistant/turns", payload())
            except RuntimeError:
                pass
        async with factory() as session:
            assert (
                await session.scalar(select(func.count()).select_from(AssistantActionRecord))
                == count
            )
        passed("model-return/commit interruption rolls back proposal and result together")

        settings.assistant_max_turns = 2
        await request(
            client, "POST", "/assistant/turns", payload(creation_id=None, conversation_id=cid), 409
        )
        settings.assistant_max_turns = 200
        async with factory.begin() as session:
            original = await session.get(AssistantTurnRecord, UUID(completed["id"]))
            original.result_version = 999
        detail = await request(client, "GET", f"/assistant/conversations/{cid}")
        assert detail["turns"][0]["reply"]["evidence"] == []
        passed("turn capacity and unknown stored version safe text fallback")

        # Stable complete-turn pagination and bounded server history.
        for index in range(23):
            gateway = Decisions(Answer(kind="answer", text=f"answer-{index}"))
            app.state.assistant_gateway = gateway
            await request(
                client,
                "POST",
                "/assistant/turns",
                payload(
                    creation_id=None,
                    conversation_id=cid,
                    question=f"question-{index}",
                    expected_context_version=3 + index,
                ),
            )
        user_messages = [message for message in gateway.messages[0] if message["role"] != "system"]
        assert len(user_messages) == 15
        latest = await request(client, "GET", f"/assistant/conversations/{cid}")
        earlier = await request(
            client, "GET", f"/assistant/conversations/{cid}?before={latest['next_before']}"
        )
        assert len(latest["turns"]) == 20 and len(earlier["turns"]) == 5
        assert earlier["turns"][-1]["sequence"] < latest["turns"][0]["sequence"]
        for index in range(23):
            app.state.assistant_gateway = Decisions(Answer(kind="answer", text="list"))
            await request(client, "POST", "/assistant/turns", payload(question=f"history-{index}"))
        listing = await request(client, "GET", "/assistant/conversations")
        await request(client, "GET", f"/assistant/conversations/{cid}")
        following = await request(
            client, "GET", f"/assistant/conversations?cursor={listing['next_cursor']}"
        )
        assert len(listing["items"]) == 20
        assert not (
            {item["id"] for item in listing["items"]} & {item["id"] for item in following["items"]}
        )
        settings.assistant_max_conversations = 1
        await request(client, "POST", "/assistant/turns", payload(), 409)
        settings.assistant_max_conversations = 100
        passed("stable conversation/turn pagination; seven-pair context bound; conversation quota")

        async with factory.begin() as session:
            before = await database_evidence(session)
            await prepare_restored_tasks(session)
            await session.flush()
            after = await database_evidence(session)
            for table in ("budgets", "transactions", "recurring_plans", "monthly_reports"):
                assert before.hashes[table] == after.hashes[table]
            applied = await session.get(AssistantActionRecord, UUID(action_id))
            assert applied.result == saved["result"]
            assert after.counts["assistant_turns"] == 0
        async with factory.begin() as session:
            await prepare_restored_tasks(session)
            await session.flush()
            assert await database_evidence(session) == after
        assert (await client.get("/api/v1/assistant/conversations")).status_code == 401
        await request(client, "POST", "/auth/login", {"email": "r2@test.com", "password": PASSWORD})
        await request(client, "POST", "/assistant/turns", data, 410)
        passed("restore clears chats; preserves business/receipts; repeat safe; replay refused")

        app.state.assistant_gateway = Decisions(Answer(kind="answer", text="Legacy readable"))
        backup_turn = await request(client, "POST", "/assistant/turns", payload())
        backup_cid = backup_turn["conversation_id"]
        await request(
            client,
            "PUT",
            f"/assistant/conversations/{backup_cid}/search-context",
            {
                "filters": {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "text": "private search",
                },
                "expected_context_version": 1,
            },
        )
        async with factory.begin() as session:
            legacy = await session.get(AssistantTurnRecord, UUID(backup_turn["id"]))
            legacy.result_version = 1
        legacy_detail = await request(client, "GET", f"/assistant/conversations/{backup_cid}")
        assert not legacy_detail["turns"][0]["reply"].get("history_unavailable")

        # Real dump/restore validates the new tables, tombstones and confirmation gate.
        import os
        import subprocess
        import tempfile
        from pathlib import Path

        import asyncpg
        from sqlalchemy.engine import make_url

        from bankpilot.services.database_backup import (
            backup_database,
            check_restored,
            restore_database,
        )

        restore_name = "bankpilot_r2_restore_" + uuid4().hex
        parsed = make_url(url)
        admin = await asyncpg.connect(
            parsed.set(drivername="postgresql", database="postgres").render_as_string(
                hide_password=False
            )
        )
        await admin.execute(f'CREATE DATABASE "{restore_name}"')
        restore_url = parsed.set(database=restore_name).render_as_string(hide_password=False)
        try:
            with tempfile.TemporaryDirectory(prefix="bankpilot-r2-backup-") as temporary:
                directory = Path(temporary) / "backup"
                await backup_database(url, directory, "local-r2-acceptance")
                await restore_database(restore_url, directory, restore_name)
                dry = await check_restored(restore_url, directory, restore_name, prepare=True)
                assert dry["database"] == restore_name
                try:
                    await check_restored(
                        restore_url, directory, restore_name, prepare=True, apply=True
                    )
                except ValueError as exc:
                    assert "clear-assistant-history" in str(exc)
                else:
                    raise AssertionError("restore missing confirmation was accepted")
                await check_restored(
                    restore_url,
                    directory,
                    restore_name,
                    prepare=True,
                    apply=True,
                    clear_assistant_history=True,
                )
                assert await check_restored(
                    restore_url,
                    directory,
                    restore_name,
                    prepare=True,
                    apply=True,
                    clear_assistant_history=True,
                ) == {"reports": 0, "runs": 0}
        finally:
            await admin.execute(f'DROP DATABASE "{restore_name}"')
            await admin.close()
        # Preserve real R2-compatible history through the additive R3 upgrade.
        for command in (("downgrade", "20260921_0013"), ("upgrade", "head")):
            await asyncio.to_thread(
                subprocess.run,
                ["uv", "run", "alembic", *command],
                env={**os.environ, "BANKPILOT_DATABASE_URL": url},
                check=True,
                stdout=subprocess.DEVNULL,
            )
        legacy_detail = await request(client, "GET", f"/assistant/conversations/{backup_cid}")
        assert legacy_detail["conversation"]["search_context"] is None
        assert legacy_detail["conversation"]["context_version"] == 0
        assert legacy_detail["turns"][0]["reply"]["text"] == "Legacy readable"
        passed(
            "R3 context backup/restore; legacy R2 result and row survive R3 migration"
        )

        # Only this disposable fixture is downgraded; no shared database is touched.
        for command in (("downgrade", "20260916_0012"), ("upgrade", "head"), ("check",)):
            await asyncio.to_thread(
                subprocess.run,
                ["uv", "run", "alembic", *command],
                env={**os.environ, "BANKPILOT_DATABASE_URL": url},
                check=True,
                stdout=subprocess.DEVNULL,
            )
        passed("20-table backup/restore and explicit cleanup gate; migration downgrade/upgrade")


if __name__ == "__main__":
    asyncio.run(main(run))
