"""R9 regressions against an explicitly selected disposable PostgreSQL database."""

import os
import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from bankpilot.api.app import create_app
from bankpilot.config import Settings
from bankpilot.db.models import BudgetRecord, MonthlyReportRecord, SessionRecord, UserRecord
from bankpilot.db.session import create_engine, create_session_factory
from bankpilot.domain.reports import REPORT_RULE_VERSION, MonthlySnapshot, ReportStatus
from bankpilot.security import hash_session_token


@unittest.skipUnless(os.getenv("BANKPILOT_TEST_DATABASE_URL"), "Requires disposable PostgreSQL")
class R9Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = os.environ["BANKPILOT_TEST_DATABASE_URL"]
        parsed = make_url(url)
        if parsed.host not in {"127.0.0.1", "localhost"} or not (parsed.database or "").startswith(
            "bankpilot_"
        ):
            raise RuntimeError("Acceptance requires an explicitly named disposable local database")
        settings = Settings(_env_file=None, BANKPILOT_DATABASE_URL=url)
        engine = create_engine(url)
        self.addAsyncCleanup(engine.dispose)
        self.factory = create_session_factory(engine)
        self.users = [uuid4(), uuid4()]
        self.headers = []
        async with self.factory.begin() as session:
            for uid in self.users:
                session.add(
                    UserRecord(id=uid, email=f"{uid}@example.com", password_hash="test-only")
                )
                token = uuid4().hex
                await session.flush()
                session.add(
                    SessionRecord(
                        user_id=uid,
                        token_hash=hash_session_token(
                            token, settings.session_secret.get_secret_value()
                        ),
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    )
                )
                self.headers.append(
                    {"X-BankPilot-User": str(uid), "Cookie": f"bankpilot_session={token}"}
                )
        self.addAsyncCleanup(self.delete_users)
        app = create_app(settings, self.factory, model_gateway=object(), assistant_gateway=object())
        app.state.security_ready = True
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local.test"
        )
        self.addAsyncCleanup(self.client.aclose)

    async def delete_users(self):
        async with self.factory.begin() as session:
            await session.execute(delete(UserRecord).where(UserRecord.id.in_(self.users)))

    async def post(self, route, payload, status=200, user=0):
        response = await self.client.post(route, json=payload, headers=self.headers[user])
        self.assertEqual(response.status_code, status, response.text)
        return response.json() if response.content else None

    async def test_template_rejects_stale_preview_and_replays_frozen_receipt(self):
        root = "/api/v1/budget-templates"
        template = {
            "id": str(uuid4()),
            "name": "Monthly limits",
            "expected_version": 0,
            "entries": [{"category": "dining", "currency": "CNY", "amount": "125.50"}],
        }
        saved = await self.post(root, template)
        self.assertEqual(await self.post(root, template), saved)
        path = f"{root}/{template['id']}"
        target = {"month": "2026-11-01", "mode": "overwrite"}
        preview = await self.post(f"{path}/preview", target)
        await self.post(f"{path}/preview", target, status=404, user=1)
        budget = "/api/v1/budgets"
        await self.post(
            budget,
            {"month": target["month"], "expected_version": 0, **template["entries"][0]},
            status=204,
        )
        apply = {**target, "operation_id": str(uuid4()), "fingerprint": preview["fingerprint"]}
        await self.post(f"{path}/apply", apply, status=409)
        template["expected_version"] = saved["version"]
        template["entries"][0]["amount"] = "150.75"
        latest = await self.post(root, template)
        preview = await self.post(f"{path}/preview", target)
        apply["fingerprint"] = preview["fingerprint"]
        receipt = await self.post(f"{path}/apply", apply)
        self.assertTrue(receipt["applied"])
        self.assertEqual(receipt["changes"][0]["after"], "150.75")
        await self.post(f"{path}/delete", {"expected_version": latest["version"]}, status=204)
        self.assertEqual(await self.post(f"{path}/apply", apply), receipt)
        async with self.factory() as session:
            row = await session.get(
                BudgetRecord, (self.users[0], date(2026, 11, 1), "dining", "CNY")
            )
            self.assertIsNotNone(row)
            self.assertEqual(row.version, 2)
            self.assertEqual(str(row.amount), "150.75")

    async def test_comparison_uses_frozen_decimal_amounts_and_rejects_other_user(self):
        start, end = date(2026, 11, 1), date(2026, 11, 30)
        now = datetime.now(UTC)
        reports = []
        async with self.factory.begin() as session:
            for index, amount in enumerate(("90071992547409.90", "90071992547409.91")):
                snapshot = MonthlySnapshot.model_validate(
                    {
                        "month": start,
                        "report_rule_version": REPORT_RULE_VERSION,
                        "ledger_revision": index,
                        "transactions": {"start_date": start, "end_date": end, "items": []},
                        "review": {
                            "snapshot_at": now,
                            "adjusted_summaries": [],
                            "relations": [],
                            "evidence": [],
                            "candidates_truncated": False,
                            "coverage": {
                                "start_date": start,
                                "end_date": end,
                                "transaction_count": 1,
                                "import_batch_count": 1,
                            },
                        },
                        "analysis": {
                            "currency_summaries": [
                                {
                                    "currency": "CNY",
                                    "income": "0",
                                    "expense": amount,
                                    "net": "-" + amount,
                                    "transaction_count": 1,
                                }
                            ],
                        },
                    }
                )
                report = MonthlyReportRecord(
                    id=uuid4(),
                    user_id=self.users[0],
                    month=start,
                    idempotency_key=uuid4(),
                    status=ReportStatus.SUCCEEDED,
                    completed_at=now,
                    ledger_revision=index,
                    rule_version=REPORT_RULE_VERSION,
                    snapshot=snapshot.model_dump(mode="json"),
                )
                session.add(report)
                reports.append(report.id)

        params = {"before_id": str(reports[0]), "after_id": str(reports[1])}
        route = "/api/v1/reports/compare"
        result = await self.client.get(route, params=params, headers=self.headers[0])
        self.assertEqual(result.status_code, 200, result.text)
        expense = next(row for row in result.json()["metrics"] if row["field"] == "expense")
        self.assertEqual(expense["before"], "90071992547409.90")
        self.assertEqual(expense["after"], "90071992547409.91")
        self.assertEqual(expense["delta"], "0.01")
        other = await self.client.get(route, params=params, headers=self.headers[1])
        self.assertEqual(other.status_code, 404, other.text)
