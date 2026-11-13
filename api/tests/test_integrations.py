"""Offline provider protocol tests plus opt-in, disposable PostgreSQL acceptance.

Run: uv run python -m unittest discover -s tests -v
DB suite requires BANKPILOT_TEST_DATABASE_URL targeting a migrated local bankpilot_* DB.
No real model, Feishu delivery, or Alipay network request is made.
"""

import asyncio
import base64
import hashlib
import json
import os
import time
import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import make_url

from bankpilot.adapters.alipay_sandbox import GATEWAY, AlipaySandbox
from bankpilot.adapters.feishu import FeishuAdapter
from bankpilot.api.app import create_app
from bankpilot.config import Settings
from bankpilot.db.models import (
    AlipayOrderRecord,
    FeishuBindingRecord,
    FeishuMessageRecord,
    SessionRecord,
    UserRecord,
)
from bankpilot.db.session import create_engine, create_session_factory
from bankpilot.domain.assistant import Answer, ReadBudgets
from bankpilot.domain.integrations import SandboxPaymentInput
from bankpilot.errors import PlanningError
from bankpilot.security import hash_session_token
from bankpilot.services import integrations as service
from bankpilot.services.account_data import export_account

APP_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PROVIDER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE = APP_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
PUBLIC = (
    PROVIDER_KEY.public_key()
    .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    .decode()
)


def settings(**overrides):
    return Settings(
        _env_file=None,
        **{
            "BANKPILOT_SESSION_COOKIE_SECURE": False,
            "BANKPILOT_PUBLIC_URL": "https://bankpilot.example.test",
            "FEISHU_ENABLED": True,
            "FEISHU_APP_ID": "cli_test",
            "FEISHU_APP_SECRET": "offline-test-secret",
            "FEISHU_ENCRYPT_KEY": "offline-encryption-key",
            "FEISHU_VERIFICATION_TOKEN": "offline-verification-token",
            "FEISHU_TENANT_KEY": "tenant-test",
            "ALIPAY_SANDBOX_ENABLED": True,
            "ALIPAY_SANDBOX_APP_ID": "sandbox-app",
            "ALIPAY_SANDBOX_SELLER_ID": "sandbox-seller",
            "ALIPAY_SANDBOX_PRIVATE_KEY": PRIVATE,
            "ALIPAY_SANDBOX_PUBLIC_KEY": PUBLIC,
            **overrides,
        },
    )


def envelope(data, stamp=None):
    stamp = str(int(time.time())) if stamp is None else str(stamp)
    iv = b"0123456789abcdef"
    key = hashlib.sha256(b"offline-encryption-key").digest()
    padder = padding.PKCS7(128).padder()
    plain = padder.update(json.dumps(data).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    body = json.dumps(
        {"encrypt": base64.b64encode(iv + encryptor.update(plain) + encryptor.finalize()).decode()}
    ).encode()
    signature = hashlib.sha256(
        (stamp + "nonce" + "offline-encryption-key").encode() + body
    ).hexdigest()
    return body, {
        "x-lark-request-timestamp": stamp,
        "x-lark-request-nonce": "nonce",
        "x-lark-signature": signature,
        "content-type": "application/json",
    }


def event(text="本月预算", *, open_id="ou_test", **message_changes):
    return {
        "schema": "2.0",
        "header": {
            "event_id": str(uuid4()),
            "event_type": "im.message.receive_v1",
            "token": "offline-verification-token",
            "app_id": "cli_test",
            "tenant_key": "tenant-test",
        },
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": open_id}},
            "message": {
                "message_id": str(uuid4()),
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": text}),
                **message_changes,
            },
        },
    }


def payment(row, **changes):
    return {
        "app_id": "sandbox-app",
        "seller_id": "sandbox-seller",
        "out_trade_no": row.id.hex,
        "total_amount": str(row.amount),
        "trade_no": "trade-" + row.id.hex,
        "trade_status": "TRADE_SUCCESS",
        **changes,
    }


def signed(data):
    data = {**data, "sign_type": "RSA2"}
    content = "&".join(
        f"{k}={v}" for k, v in sorted(data.items()) if k not in {"sign", "sign_type"} and v
    )
    return {
        **data,
        "sign": base64.b64encode(
            PROVIDER_KEY.sign(content.encode(), rsa_padding.PKCS1v15(), hashes.SHA256())
        ).decode(),
    }


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def test_disabled_and_incomplete_configuration(self):
        self.assertFalse(Settings(_env_file=None).feishu_enabled)
        self.assertFalse(Settings(_env_file=None).alipay_sandbox_enabled)
        for change in (
            {"FEISHU_APP_SECRET": ""},
            {"BANKPILOT_PUBLIC_URL": "http://example.test"},
            {"BANKPILOT_PUBLIC_URL": "https://example.test/path"},
            {"ALIPAY_SANDBOX_SELLER_ID": ""},
        ):
            with self.assertRaises(ValidationError):
                settings(**change)
        with self.assertRaises(ValueError):
            AlipaySandbox(settings(ALIPAY_SANDBOX_PUBLIC_KEY="broken"))

    async def test_encrypted_event_authentication(self):
        async with httpx.AsyncClient() as client:
            adapter = FeishuAdapter(settings(), client)
            data = event()
            body, headers = envelope(data)
            self.assertEqual(adapter.event(body, headers), data)
            for content, fields in (
                (body, {**headers, "x-lark-signature": "bad"}),
                envelope(data, int(time.time()) - 301),
                (b'{"event": {}}', headers),
                (b"[]", headers),
            ):
                with self.assertRaises(PlanningError):
                    adapter.event(content, fields)
            for key in ("tenant_key", "app_id", "token"):
                broken = event()
                broken["header"][key] = "wrong"
                with self.assertRaises(PlanningError):
                    adapter.event(*envelope(broken))
            challenge = {
                "type": "url_verification",
                "token": "offline-verification-token",
                "challenge": "challenge-123",
            }
            body, _ = envelope(challenge)
            self.assertEqual(adapter.event(body, {})["challenge"], "challenge-123")
            challenge["token"] = "wrong"
            with self.assertRaises(PlanningError):
                adapter.event(*envelope(challenge))

    def test_checkout_is_signed_sandbox_only(self):
        adapter = AlipaySandbox(settings())
        row = AlipayOrderRecord(
            id=uuid4(),
            subject='含中文 & "测试"',
            amount=Decimal("1.23"),
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        url = adapter.checkout(row)
        self.assertTrue(url.startswith(GATEWAY + "?"))
        params = dict(parse_qsl(urlsplit(url).query))
        content = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "sign")
        APP_KEY.public_key().verify(
            base64.b64decode(params["sign"]),
            content.encode(),
            rsa_padding.PKCS1v15(),
            hashes.SHA256(),
        )
        biz = json.loads(params["biz_content"])
        self.assertEqual(biz["total_amount"], "1.23")
        self.assertEqual(biz["out_trade_no"], row.id.hex)
        self.assertEqual(biz["subject"], row.subject)
        self.assertTrue(params["notify_url"].endswith("/api/v1/integrations/alipay/notify"))
        self.assertNotIn("return_url", params)

    async def test_official_sdk_verifies_query_response(self):
        adapter = AlipaySandbox(settings())
        result = {
            "code": "10000",
            "out_trade_no": uuid4().hex,
            "total_amount": "1.00",
            "trade_status": "TRADE_SUCCESS",
            "trade_no": "trade-test",
        }
        raw = json.dumps(result, ensure_ascii=False)
        signature = base64.b64encode(
            PROVIDER_KEY.sign(raw.encode(), rsa_padding.PKCS1v15(), hashes.SHA256())
        ).decode()
        response = (
            '{"alipay_trade_query_response":' + raw + ',"sign":"' + signature + '"}'
        ).encode()
        with patch("alipay.aop.api.DefaultAlipayClient.do_post", return_value=response):
            self.assertEqual(await adapter.query(result["out_trade_no"]), result)
        with patch(
            "alipay.aop.api.DefaultAlipayClient.do_post",
            return_value=response.replace(b"1.00", b"2.00"),
        ):
            with self.assertRaises(PlanningError):
                await adapter.query(result["out_trade_no"])

    async def test_checkout_and_query_use_shanghai_time_in_utc_process(self):
        # Exercise the actual SDK's signing path, rather than replacing its client.
        previous_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        try:
            adapter = AlipaySandbox(settings(BANKPILOT_TIMEZONE="America/New_York"))
            row = AlipayOrderRecord(
                id=uuid4(),
                subject="UTC test",
                amount=Decimal("1.00"),
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
            checkout = dict(parse_qsl(urlsplit(adapter.checkout(row)).query))
            raw = json.dumps({"code": "10000"})
            signature = base64.b64encode(
                PROVIDER_KEY.sign(raw.encode(), rsa_padding.PKCS1v15(), hashes.SHA256())
            ).decode()
            response = (
                '{"alipay_trade_query_response":' + raw + ',"sign":"' + signature + '"}'
            ).encode()
            with patch("alipay.aop.api.DefaultAlipayClient.do_post", return_value=response) as post:
                await adapter.query(row.id.hex)
            query = dict(parse_qsl(post.call_args.args[1]))
            for params in (checkout, query):
                with self.subTest(method=params["method"]):
                    signed_at = datetime.strptime(params["timestamp"], "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=ZoneInfo("Asia/Shanghai")
                    )
                    self.assertLess(abs((datetime.now(UTC) - signed_at).total_seconds()), 5)
                    business = (
                        dict(parse_qsl(post.call_args.args[3]))
                        if isinstance(post.call_args.args[3], str)
                        else post.call_args.args[3]
                    )
                    all_params = {**params, **business} if params is query else params
                    content = "&".join(
                        f"{k}={v}" for k, v in sorted(all_params.items()) if k != "sign"
                    )
                    APP_KEY.public_key().verify(
                        base64.b64decode(params["sign"]),
                        content.encode(),
                        rsa_padding.PKCS1v15(),
                        hashes.SHA256(),
                    )
            self.assertEqual(os.environ["TZ"], "UTC")
            self.assertEqual(time.localtime().tm_hour, datetime.now(UTC).hour)
        finally:
            if previous_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous_tz
            time.tzset()

    def test_full_refund_closes_paid_order_and_late_success_cannot_reopen_it(self):
        config = settings()
        for notification in (False, True):
            with self.subTest(notification=notification):
                row = AlipayOrderRecord(
                    id=uuid4(),
                    app_id=config.alipay_app_id,
                    seller_id=config.alipay_seller_id,
                    amount=Decimal("1.00"),
                    status="TRADE_SUCCESS",
                )
                service.apply_payment(
                    row,
                    payment(row, trade_status="TRADE_CLOSED"),
                    config,
                    notification=notification,
                )
                self.assertEqual(row.status, "TRADE_CLOSED")
                for late in ("WAIT_BUYER_PAY", "TRADE_SUCCESS", "TRADE_FINISHED", "TRADE_CLOSED"):
                    service.apply_payment(
                        row, payment(row, trade_status=late), config, notification=True
                    )
                    self.assertEqual(row.status, "TRADE_CLOSED")

    def test_notification_verification_and_state_integrity(self):
        adapter = AlipaySandbox(settings())
        row = AlipayOrderRecord(
            id=uuid4(),
            app_id="sandbox-app",
            seller_id="sandbox-seller",
            subject="test",
            amount=Decimal("1.00"),
            status="WAIT_BUYER_PAY",
        )
        data = signed(payment(row))
        adapter.verify(data)
        for change in ({"total_amount": "999.00"}, {"sign_type": "RSA"}, {"sign": "bad"}):
            with self.assertRaises(PlanningError):
                adapter.verify({**data, **change})
        for change in (
            {"total_amount": "2.00"},
            {"total_amount": "NaN"},
            {"app_id": "wrong"},
            {"seller_id": "wrong"},
            {"out_trade_no": uuid4().hex},
            {"trade_status": "UNKNOWN"},
        ):
            with self.assertRaises(PlanningError):
                service.apply_payment(row, payment(row, **change), settings(), notification=True)
            self.assertEqual(row.status, "WAIT_BUYER_PAY")
        service.apply_payment(row, payment(row), settings(), notification=True)
        self.assertEqual(row.status, "TRADE_SUCCESS")
        service.apply_payment(
            row, payment(row, trade_status="WAIT_BUYER_PAY"), settings(), notification=True
        )
        self.assertEqual(row.status, "TRADE_SUCCESS")
        service.apply_payment(
            row, payment(row, trade_status="TRADE_FINISHED"), settings(), notification=True
        )
        self.assertEqual(row.status, "TRADE_FINISHED")
        for late in ("WAIT_BUYER_PAY", "TRADE_SUCCESS", "TRADE_CLOSED"):
            service.apply_payment(
                row, payment(row, trade_status=late), settings(), notification=True
            )
            self.assertEqual(row.status, "TRADE_FINISHED")
        with self.assertRaises(PlanningError):
            service.apply_payment(
                row, payment(row, trade_no="other"), settings(), notification=True
            )

    def test_payment_validation(self):
        base = {
            "operation_id": uuid4(),
            "subject": "测试",
            "amount": "1.00",
            "confirmation": "确认沙箱支付",
        }
        for change in (
            {"amount": "0"},
            {"amount": "10000.01"},
            {"amount": "1.001"},
            {"amount": "NaN"},
            {"confirmation": "确认"},
            {"subject": "\n"},
            {"extra": "field"},
        ):
            with self.assertRaises(ValidationError):
                SandboxPaymentInput.model_validate({**base, **change})


class OfflineAssistant:
    def __init__(self):
        self.calls = 0

    async def decide(self, messages):
        self.calls += 1
        if self.calls % 2:
            return ReadBudgets(kind="budgets", arguments={"month": date.today().replace(day=1)})
        return Answer(kind="answer", text="已读取本月预算；尚无导入数据。")


@unittest.skipUnless(
    os.getenv("BANKPILOT_TEST_DATABASE_URL"), "Requires disposable local PostgreSQL"
)
class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = os.environ["BANKPILOT_TEST_DATABASE_URL"]
        parsed = make_url(url)
        if parsed.host not in {"127.0.0.1", "localhost"} or not (parsed.database or "").startswith(
            "bankpilot_"
        ):
            raise RuntimeError("Acceptance requires an explicitly named disposable local database")
        self.settings = settings(BANKPILOT_DATABASE_URL=url)
        self.engine = create_engine(url)
        self.factory = create_session_factory(self.engine)
        self.factory.configure(info={"notification_settings": self.settings})
        self.users, self.tokens = [], []
        async with self.factory.begin() as session:
            for _ in range(2):
                user = UserRecord(
                    id=uuid4(),
                    email=f"{uuid4()}@example.test",
                    password_hash="offline-no-password-login",
                )
                token = str(uuid4())
                session.add(user)
                await session.flush()
                session.add(
                    SessionRecord(
                        user_id=user.id,
                        token_hash=hash_session_token(
                            token, self.settings.session_secret.get_secret_value()
                        ),
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    )
                )
                self.users.append(user)
                self.tokens.append(token)
        self.sent = []

        def provider(request):
            self.assertEqual(request.url.host, "open.feishu.cn")
            if "tenant_access_token" in request.url.path:
                return httpx.Response(
                    200, json={"code": 0, "tenant_access_token": "offline-token", "expire": 7200}
                )
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json={"code": 0})

        self.provider_client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
        self.feishu = FeishuAdapter(self.settings, self.provider_client)
        self.alipay = AlipaySandbox(self.settings)
        self.gateway = OfflineAssistant()
        self.app = create_app(
            self.settings, self.factory, model_gateway=object(), assistant_gateway=self.gateway
        )
        self.app.state.feishu, self.app.state.alipay_sandbox = self.feishu, self.alipay
        self.app.state.security_ready = True
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://local.test"
        )
        self.processor = service.FeishuProcessor(
            self.factory, self.settings, self.feishu, self.gateway
        )

    async def asyncTearDown(self):
        async with self.factory.begin() as session:
            for user in self.users:
                from sqlalchemy import delete

                await session.execute(delete(UserRecord).where(UserRecord.id == user.id))
        await self.client.aclose()
        await self.provider_client.aclose()
        await self.engine.dispose()

    def auth(self, index=0):
        return {
            "X-BankPilot-User": str(self.users[index].id),
            "Cookie": f"bankpilot_session={self.tokens[index]}",
        }

    async def post_event(self, data):
        body, headers = envelope(data)
        return await self.client.post(
            "/api/v1/integrations/feishu/events", content=body, headers=headers
        )

    async def bind(self, index=0, open_id=None):
        open_id = open_id or f"ou_{self.users[index].id.hex}"
        result = await self.client.post(
            "/api/v1/integrations/feishu/binding-code", headers=self.auth(index)
        )
        self.assertEqual(result.status_code, 200, result.text)
        code = result.json()["code"]
        data = event("绑定 " + code, open_id=open_id)
        result = await self.post_event(data)
        self.assertEqual(result.status_code, 200, result.text)
        return open_id, code, data

    async def test_binding_dedup_query_isolation_unlink(self):
        self.assertEqual((await self.client.get("/api/v1/integrations")).status_code, 401)
        wrong = await self.client.get(
            "/api/v1/integrations",
            headers={**self.auth(), "X-BankPilot-User": str(self.users[1].id)},
        )
        self.assertEqual(wrong.status_code, 409)
        open_id, code, data = await self.bind()
        self.assertEqual((await self.post_event(data)).status_code, 200)
        status = (await self.client.get("/api/v1/integrations", headers=self.auth())).json()
        self.assertTrue(status["feishu_bound"])
        self.assertFalse(
            (await self.client.get("/api/v1/integrations", headers=self.auth(1))).json()[
                "feishu_bound"
            ]
        )
        async with self.factory() as session:
            binding = await session.get(FeishuBindingRecord, self.users[0].id)
            self.assertIsNone(binding.code_hash)
            self.assertEqual(
                await session.scalar(
                    select(func.count())
                    .select_from(FeishuMessageRecord)
                    .where(FeishuMessageRecord.user_id == self.users[0].id)
                ),
                1,
            )
            exported = await export_account(session, self.users[0].id)
            self.assertNotIn(code, json.dumps(exported))
        self.assertTrue(await self.processor.process_one())
        self.assertEqual(self.gateway.calls, 0)
        self.assertEqual(self.sent[-1]["receive_id"], open_id)
        question = event(open_id=open_id)
        self.assertEqual((await self.post_event(question)).status_code, 200)
        await self.processor.process_one()
        self.assertEqual(self.gateway.calls, 2)
        self.assertIn("本月预算", self.sent[-1]["content"])
        self.assertEqual((await self.post_event(question)).status_code, 200)
        self.assertFalse(await self.processor.process_one())
        # Provider can retry the same message using a different event ID.
        question["header"]["event_id"] = str(uuid4())
        self.assertEqual((await self.post_event(question)).status_code, 200)
        self.assertFalse(await self.processor.process_one())
        before = len(self.sent)
        await self.post_event(event(open_id=open_id))
        result = await self.client.post("/api/v1/integrations/feishu/unbind", headers=self.auth())
        self.assertEqual(result.status_code, 204)
        self.assertFalse(await self.processor.process_one())
        self.assertEqual(len(self.sent), before)
        await self.post_event(event(open_id=open_id))
        self.assertFalse(await self.processor.process_one())
        async with self.factory() as session:
            self.assertEqual((await session.get(UserRecord, self.users[0].id)).ledger_revision, 0)

    async def test_unsupported_and_expired_binding(self):
        open_id, _, _ = await self.bind()
        await self.processor.process_one()
        for data in (
            event(open_id=open_id, chat_type="group"),
            event(open_id=open_id, message_type="image"),
            event(open_id="unbound"),
        ):
            self.assertEqual((await self.post_event(data)).status_code, 200)
        self.assertFalse(await self.processor.process_one())

        result = await self.client.post(
            "/api/v1/integrations/feishu/binding-code", headers=self.auth(1)
        )
        code = result.json()["code"]
        # A Feishu identity cannot silently switch to another local user's ledger.
        await self.post_event(event("绑定 " + code, open_id=open_id))
        async with self.factory.begin() as session:
            self.assertIsNone((await session.get(FeishuBindingRecord, self.users[1].id)).open_id)
            await session.execute(
                update(FeishuBindingRecord)
                .where(FeishuBindingRecord.user_id == self.users[1].id)
                .values(code_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        await self.post_event(event("绑定 " + code, open_id="other"))
        self.assertFalse(await self.processor.process_one())

    async def test_concurrent_binding_claims_keep_one_owner_without_deadlock(self):
        codes = []
        for index in range(2):
            response = await self.client.post(
                "/api/v1/integrations/feishu/binding-code", headers=self.auth(index)
            )
            self.assertEqual(response.status_code, 200)
            codes.append(response.json()["code"])
        shared_identity = "ou_claim_" + uuid4().hex
        results = await asyncio.wait_for(
            asyncio.gather(
                *(self.post_event(event("绑定 " + code, open_id=shared_identity)) for code in codes)
            ),
            timeout=3,
        )
        self.assertEqual([result.status_code for result in results], [200, 200])
        async with self.factory() as session:
            bindings = (
                await session.scalars(
                    select(FeishuBindingRecord).where(
                        FeishuBindingRecord.user_id.in_([user.id for user in self.users])
                    )
                )
            ).all()
            owners = [row for row in bindings if row.open_id == shared_identity]
            self.assertEqual(len(owners), 1)
            self.assertEqual(
                await session.scalar(
                    select(func.count())
                    .select_from(FeishuMessageRecord)
                    .where(FeishuMessageRecord.user_id.in_([user.id for user in self.users]))
                ),
                1,
            )
            self.assertIsNone(owners[0].code_hash)

    async def test_stale_binding_cancels_with_one_database_connection(self):
        import asyncio

        from sqlalchemy.ext.asyncio import create_async_engine

        await self.bind()
        async with self.factory.begin() as session:
            row = await session.get(FeishuBindingRecord, self.users[0].id)
            row.generation = uuid4()
        engine = create_async_engine(
            self.settings.database_url, pool_size=1, max_overflow=0, pool_timeout=0.5
        )
        try:
            processor = service.FeishuProcessor(
                create_session_factory(engine), self.settings, self.feishu, self.gateway
            )
            await asyncio.wait_for(processor.process_one(), timeout=3)
        finally:
            await engine.dispose()
        async with self.factory() as session:
            row = await session.scalar(
                select(FeishuMessageRecord).where(FeishuMessageRecord.user_id == self.users[0].id)
            )
            self.assertEqual(row.status, "cancelled")
        self.assertEqual(self.sent, [])

    async def test_failed_delivery_recovers_without_repeating_model(self):
        open_id, _, _ = await self.bind()
        await self.processor.process_one()
        await self.post_event(event(open_id=open_id))
        from unittest.mock import AsyncMock

        failed = AsyncMock(side_effect=PlanningError("feishu_delivery_failed", 502))
        with patch.object(self.feishu, "send", failed):
            await self.processor.process_one()
        self.assertEqual(self.gateway.calls, 2)
        identity = failed.call_args.args[2]
        async with self.factory.begin() as session:
            await session.execute(
                update(FeishuMessageRecord)
                .where(
                    FeishuMessageRecord.user_id == self.users[0].id,
                    FeishuMessageRecord.status == "processing",
                )
                .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
            )
        # A fresh worker resumes the persisted answer with the same provider dedup UUID.
        fresh = service.FeishuProcessor(self.factory, self.settings, self.feishu, self.gateway)
        await fresh.process_one()
        self.assertEqual(self.gateway.calls, 2)
        self.assertEqual(self.sent[-1]["uuid"], identity)
        async with self.factory() as session:
            row = await session.scalar(
                select(FeishuMessageRecord)
                .where(FeishuMessageRecord.user_id == self.users[0].id)
                .order_by(FeishuMessageRecord.created_at.desc())
                .limit(1)
            )
            self.assertEqual(row.status, "sent")
            self.assertEqual(row.question, "")
            self.assertIsNone(row.reply)

    async def test_callback_waiting_for_owner_does_not_block_global_admission(self):
        import asyncio

        from bankpilot.db.assistant_repository import lock_owner

        open_id, _, _ = await self.bind()

        async def receive():
            async with self.factory.begin() as session:
                await service.receive(session, self.settings, event(open_id=open_id))

        async with self.factory.begin() as owner_session:
            await lock_owner(owner_session, self.users[0].id)
            task = asyncio.create_task(receive())
            await asyncio.sleep(0.05)
            # An unrelated user's admission remains available while this owner is busy.
            async with self.factory.begin() as another_session:
                await asyncio.wait_for(
                    service.limited(another_session, self.settings, self.users[1].id, "binding"),
                    timeout=1,
                )
        await asyncio.wait_for(task, timeout=3)

    async def test_unlink_during_model_prevents_old_reply(self):
        import asyncio

        entered, proceed = asyncio.Event(), asyncio.Event()

        class BlockingAssistant:
            async def decide(self, messages):
                entered.set()
                await proceed.wait()
                return Answer(kind="answer", text="旧绑定的回复")

        open_id, _, _ = await self.bind()
        await self.processor.process_one()
        await self.post_event(event(open_id=open_id))
        processor = service.FeishuProcessor(
            self.factory, self.settings, self.feishu, BlockingAssistant()
        )
        task = asyncio.create_task(processor.process_one())
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            result = await self.client.post(
                "/api/v1/integrations/feishu/unbind", headers=self.auth()
            )
            self.assertEqual(result.status_code, 204)
        finally:
            proceed.set()
        await task
        self.assertEqual(len(self.sent), 1)

    async def test_slow_delivery_callback_does_not_block_other_user_admission(self):
        open_id, _, _ = await self.bind()
        sending, release = asyncio.Event(), asyncio.Event()
        receiver_pid = asyncio.get_running_loop().create_future()

        async def paused_send(*args):
            sending.set()
            await release.wait()

        async def competing_write():
            async with self.factory.begin() as session:
                receiver_pid.set_result(await session.scalar(select(func.pg_backend_pid())))
                await service.receive(session, self.settings, event(open_id=open_id))

        with patch.object(self.feishu, "send", side_effect=paused_send):
            delivery = asyncio.create_task(self.processor.process_one())
            pending = None
            try:
                await asyncio.wait_for(sending.wait(), 3)
                pending = asyncio.create_task(competing_write())
                pid = await asyncio.wait_for(receiver_pid, 3)
                # Observe the actual PostgreSQL lock wait before probing user B.
                async with asyncio.timeout(3):
                    async with self.factory() as observer:
                        while (
                            await observer.scalar(
                                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"),
                                {"pid": pid},
                            )
                            != "Lock"
                        ):
                            await observer.rollback()
                            await asyncio.sleep(0.01)
                async with self.factory.begin() as other:
                    await asyncio.wait_for(
                        service.limited(other, self.settings, self.users[1].id, "binding"), 0.5
                    )
            finally:
                release.set()
                await asyncio.wait_for(delivery, 3)
                if pending is not None:
                    await asyncio.wait_for(pending, 3)
        self.assertEqual(self.gateway.calls, 0)

    async def test_delivery_retries_stop_at_three(self):
        from unittest.mock import AsyncMock

        await self.bind()
        failed = AsyncMock(side_effect=PlanningError("feishu_delivery_failed", 502))
        with patch.object(self.feishu, "send", failed):
            for _ in range(4):
                await self.processor.process_one()
                async with self.factory.begin() as session:
                    await session.execute(
                        update(FeishuMessageRecord)
                        .where(FeishuMessageRecord.user_id == self.users[0].id)
                        .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
                    )
        self.assertEqual(failed.call_count, 3)
        async with self.factory() as session:
            row = await session.scalar(
                select(FeishuMessageRecord).where(FeishuMessageRecord.user_id == self.users[0].id)
            )
            self.assertEqual(row.status, "failed")
            self.assertEqual(row.question, "")
            self.assertIsNone(row.reply)

    async def test_provider_callbacks_fail_closed_when_instance_unready(self):
        self.app.state.security_ready = False
        self.assertEqual((await self.post_event(event())).status_code, 503)
        result = await self.client.post("/api/v1/integrations/alipay/notify", content="x=y")
        self.assertEqual(result.status_code, 503)

    async def test_password_change_revokes_feishu_binding_and_pending_replies(self):
        from bankpilot.security import hash_password

        async with self.factory.begin() as session:
            user = await session.get(UserRecord, self.users[0].id)
            user.password_hash = hash_password("Old-password-A1!")
        await self.bind()
        response = await self.client.post(
            "/api/v1/auth/password",
            json={"current_password": "Old-password-A1!", "new_password": "New-password-A2!"},
            headers=self.auth(),
        )
        self.assertEqual(response.status_code, 204, response.text)
        async with self.factory() as session:
            self.assertIsNone(await session.get(FeishuBindingRecord, self.users[0].id))
            self.assertEqual(
                await session.scalar(
                    select(func.count())
                    .select_from(FeishuMessageRecord)
                    .where(FeishuMessageRecord.user_id == self.users[0].id)
                ),
                0,
            )

    async def test_restore_preparation_revokes_external_authorization(self):
        from bankpilot.services.restore_validation import prepare_restored_tasks

        await self.bind()
        async with self.factory.begin() as session:
            await prepare_restored_tasks(session)
        async with self.factory() as session:
            self.assertIsNone(await session.get(FeishuBindingRecord, self.users[0].id))
            self.assertEqual(
                await session.scalar(select(func.count()).select_from(FeishuMessageRecord)), 0
            )

    async def test_sandbox_order_callbacks_and_ownership(self):
        payload = {
            "operation_id": str(uuid4()),
            "amount": "1.23",
            "subject": "本地沙箱验收",
            "confirmation": "确认沙箱支付",
        }
        result = await self.client.post(
            "/api/v1/integrations/alipay/orders", json=payload, headers=self.auth()
        )
        self.assertEqual(result.status_code, 200, result.text)
        order = result.json()
        again = await self.client.post(
            "/api/v1/integrations/alipay/orders", json=payload, headers=self.auth()
        )
        self.assertEqual(again.json()["id"], order["id"])
        conflict = await self.client.post(
            "/api/v1/integrations/alipay/orders",
            json={**payload, "amount": "2.00"},
            headers=self.auth(),
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(
            (
                await self.client.get("/api/v1/integrations/alipay/orders", headers=self.auth(1))
            ).json(),
            [],
        )
        stolen = await self.client.post(
            f"/api/v1/integrations/alipay/orders/{order['id']}/query", headers=self.auth(1)
        )
        self.assertEqual(stolen.status_code, 404)
        async with self.factory() as session:
            row = await session.get(AlipayOrderRecord, order["id"])
        data = signed(payment(row))

        async def notify(params, raw=None):
            return await self.client.post(
                "/api/v1/integrations/alipay/notify",
                content=raw or urlencode(params),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )

        self.assertEqual((await notify({**data, "total_amount": "8.00"})).status_code, 401)
        self.assertEqual((await notify(signed(payment(row, total_amount="8.00")))).status_code, 409)
        self.assertEqual((await notify(signed(payment(row, seller_id="wrong")))).status_code, 409)
        self.assertEqual(
            (await notify(data, urlencode(data) + "&total_amount=1.23")).status_code, 422
        )
        for _ in range(2):
            result = await notify(data)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.text, "success")
        self.assertEqual(
            (await notify(signed(payment(row, trade_status="WAIT_BUYER_PAY")))).status_code, 200
        )
        listed = (
            await self.client.get("/api/v1/integrations/alipay/orders", headers=self.auth())
        ).json()
        self.assertEqual(listed[0]["status"], "TRADE_SUCCESS")
        response = payment(row, trade_status="TRADE_FINISHED")
        with patch.object(self.alipay, "query", return_value={"code": "10000", **response}):
            result = await self.client.post(
                f"/api/v1/integrations/alipay/orders/{row.id}/query", headers=self.auth()
            )
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["status"], "TRADE_FINISHED")
        async with self.factory() as session:
            self.assertEqual((await session.get(UserRecord, self.users[0].id)).ledger_revision, 0)
            self.assertEqual(
                await session.scalar(
                    select(func.count())
                    .select_from(AlipayOrderRecord)
                    .where(AlipayOrderRecord.user_id == self.users[0].id)
                ),
                1,
            )

    async def test_refund_close_by_callback_or_query_survives_late_payment_results(self):
        for source in ("callback", "query"):
            with self.subTest(source=source):
                created = await self.client.post(
                    "/api/v1/integrations/alipay/orders",
                    headers=self.auth(),
                    json={
                        "operation_id": str(uuid4()),
                        "subject": "退款状态验收",
                        "amount": "1.23",
                        "confirmation": "确认沙箱支付",
                    },
                )
                self.assertEqual(created.status_code, 200, created.text)
                async with self.factory() as session:
                    row = await session.get(AlipayOrderRecord, created.json()["id"])

                async def notify(status, row=row):
                    result = await self.client.post(
                        "/api/v1/integrations/alipay/notify",
                        content=urlencode(signed(payment(row, trade_status=status))),
                        headers={"content-type": "application/x-www-form-urlencoded"},
                    )
                    self.assertEqual(result.status_code, 200, result.text)

                async def query(status, row=row):
                    with patch.object(
                        self.alipay,
                        "query",
                        return_value={
                            "code": "10000",
                            **payment(row, trade_status=status),
                        },
                    ):
                        result = await self.client.post(
                            f"/api/v1/integrations/alipay/orders/{row.id}/query",
                            headers=self.auth(),
                        )
                    self.assertEqual(result.status_code, 200, result.text)
                    return result.json()["status"]

                await notify("TRADE_SUCCESS")
                if source == "callback":
                    await notify("TRADE_CLOSED")
                else:
                    self.assertEqual(await query("TRADE_CLOSED"), "TRADE_CLOSED")
                # Out-of-order old callbacks and an earlier in-flight query cannot reopen it.
                for late in ("TRADE_SUCCESS", "WAIT_BUYER_PAY", "TRADE_CLOSED"):
                    await notify(late)
                self.assertEqual(await query("TRADE_SUCCESS"), "TRADE_CLOSED")
                async with self.factory() as session:
                    self.assertEqual(
                        (await session.get(AlipayOrderRecord, row.id)).status, "TRADE_CLOSED"
                    )
                    self.assertEqual(
                        (await session.get(UserRecord, self.users[0].id)).ledger_revision, 0
                    )


if __name__ == "__main__":
    unittest.main()
