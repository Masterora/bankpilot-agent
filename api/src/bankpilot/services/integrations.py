"""Durable Feishu inbox and sandbox order state. External results never write the ledger."""

import asyncio
import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.adapters.alipay_sandbox import AlipaySandbox, sdk_work
from bankpilot.adapters.feishu import FeishuAdapter
from bankpilot.config import Settings
from bankpilot.db.assistant_repository import lock_owner
from bankpilot.db.models import AlipayOrderRecord, FeishuBindingRecord, FeishuMessageRecord
from bankpilot.domain.assistant import TurnInput
from bankpilot.domain.integrations import SandboxOrderView, SandboxPaymentInput
from bankpilot.errors import PlanningError
from bankpilot.ports import AssistantGateway
from bankpilot.services.conversations import ConversationService
from bankpilot.services.security_admission import consume, locked_now

logger = logging.getLogger(__name__)


async def limited(session: AsyncSession, settings: Settings, uid: UUID, action: str) -> datetime:
    now = await locked_now(session)
    await consume(
        session,
        settings,
        now,
        [(f"integration:{action}:{uid}", 10, 1), (f"integration:{action}:global", 120, 1)],
        60,
        "integration_rate_limited",
    )
    return now


async def binding_code(session: AsyncSession, settings: Settings, uid: UUID) -> dict[str, str]:
    await lock_owner(session, uid)
    now = await limited(session, settings, uid, "binding")
    row = await session.get(FeishuBindingRecord, uid)
    if (
        row
        and row.open_id
        and row.app_id == settings.feishu_app_id
        and row.tenant_key == settings.feishu_tenant_key
    ):
        raise PlanningError("feishu_already_bound", 409)
    if row is None:
        row = FeishuBindingRecord(
            user_id=uid, app_id=settings.feishu_app_id, tenant_key=settings.feishu_tenant_key
        )
        session.add(row)
    if row.app_id != settings.feishu_app_id or row.tenant_key != settings.feishu_tenant_key:
        row.open_id, row.generation = None, uuid4()
    code = secrets.token_urlsafe(24)
    row.code_hash = hashlib.sha256(code.encode()).hexdigest()
    row.code_expires_at = now + timedelta(minutes=5)
    row.app_id, row.tenant_key = settings.feishu_app_id, settings.feishu_tenant_key
    return {"code": code, "expires_at": row.code_expires_at.isoformat()}


async def unbind(session: AsyncSession, uid: UUID) -> None:
    await lock_owner(session, uid)
    row = await session.get(FeishuBindingRecord, uid, with_for_update=True)
    if row:
        await session.delete(row)
    # Remove undelivered private content immediately; workers recheck generation before sending.
    await session.execute(delete(FeishuMessageRecord).where(FeishuMessageRecord.user_id == uid))


async def receive(session: AsyncSession, settings: Settings, data: dict[str, Any]) -> None:
    header, event = data.get("header", {}), data.get("event", {})
    if header.get("event_type") != "im.message.receive_v1":
        return
    try:
        sender, message = event["sender"], event["message"]
        if (
            sender.get("sender_type") != "user"
            or message.get("chat_type") != "p2p"
            or message.get("message_type") != "text"
        ):
            return
        open_id = sender["sender_id"]["open_id"]
        event_id, message_id = header["event_id"], message["message_id"]
        question = json.loads(message["content"])["text"].strip()
        if (
            not all(
                isinstance(item, str) and 0 < len(item) <= 128
                for item in (open_id, event_id, message_id)
            )
            or not 0 < len(question) <= 1000
        ):
            return
    except (ValueError, KeyError, TypeError, AttributeError):
        raise PlanningError("feishu_event_invalid", 422) from None
    code_hash = (
        hashlib.sha256(question[3:].strip().encode()).hexdigest()
        if question.startswith("绑定 ")
        else None
    )
    probe = select(FeishuBindingRecord.user_id).where(
        FeishuBindingRecord.app_id == settings.feishu_app_id,
        FeishuBindingRecord.tenant_key == settings.feishu_tenant_key,
        FeishuBindingRecord.code_hash == code_hash
        if code_hash
        else FeishuBindingRecord.open_id == open_id,
    )
    uid = await session.scalar(probe)
    if uid is None:
        return
    # Wait for the owner and binding before taking shared admission. Delivery holds
    # the binding across HTTP, so waiting in the reverse order stalls unrelated users.
    await lock_owner(session, uid)
    row = await session.get(FeishuBindingRecord, uid, with_for_update=True)
    if (
        row is None
        or row.app_id != settings.feishu_app_id
        or row.tenant_key != settings.feishu_tenant_key
        or (not code_hash and row.open_id != open_id)
    ):
        return
    now = await locked_now(session)
    reply = None
    if code_hash:
        # All binding claims are serialized by admission. Read other identities
        # without locking another user's binding, which could invert owner locks.
        other_owner = await session.scalar(
            select(FeishuBindingRecord.user_id).where(
                FeishuBindingRecord.open_id == open_id,
                FeishuBindingRecord.user_id != uid,
            )
        )
        if (
            other_owner is not None
            or row.code_hash != code_hash
            or row.code_expires_at is None
            or row.code_expires_at <= now
        ):
            return
        row.open_id, row.code_hash, row.code_expires_at = open_id, None, None
        reply = (
            "绑定成功。可以私聊查询账本；预算修改需回到 BankPilot 页面确认。发送“帮助”查看用法。"
        )
        question = "绑定账号"  # Never retain the one-time code.
    if question in {"帮助", "help"}:
        reply = (
            "可询问：本月花了多少、餐饮支出、预算还剩多少。"
            "每条消息独立查询当前月份；需要上下文或确认预算提案时，"
            "请到 BankPilot 助手历史。支付只在网页中确认。"
        )
    duplicate = await session.scalar(
        select(FeishuMessageRecord.id).where(
            or_(FeishuMessageRecord.id == event_id, FeishuMessageRecord.message_id == message_id)
        )
    )
    if duplicate:
        return
    count = await session.scalar(
        select(func.count())
        .select_from(FeishuMessageRecord)
        .where(FeishuMessageRecord.status.in_(("queued", "processing")))
    )
    if count is not None and count >= 1000:
        raise PlanningError("feishu_queue_full", 429)
    await consume(
        session,
        settings,
        now,
        [(f"integration:feishu:{row.user_id}", 10, 1), ("integration:feishu:global", 120, 1)],
        60,
        "integration_rate_limited",
    )
    await session.execute(
        insert(FeishuMessageRecord)
        .values(
            id=event_id,
            message_id=message_id,
            user_id=row.user_id,
            binding_generation=row.generation,
            question=question,
            month=now.astimezone(ZoneInfo(settings.business_timezone)).date().replace(day=1),
            reply=reply,
            status="queued",
            attempts=0,
        )
        .on_conflict_do_nothing()
    )


class FeishuProcessor:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        adapter: FeishuAdapter,
        gateway: AssistantGateway,
    ) -> None:
        self.factory, self.settings, self.adapter, self.gateway = (
            factory,
            settings,
            adapter,
            gateway,
        )

    async def process_one(self) -> bool:
        async with self.factory.begin() as session:
            now = (await session.execute(select(func.clock_timestamp()))).scalar_one()
            # Bound retention, including answers; conversation history follows existing quotas.
            await session.execute(
                delete(FeishuMessageRecord).where(
                    FeishuMessageRecord.created_at < now - timedelta(days=7),
                    FeishuMessageRecord.status.in_(("sent", "failed", "cancelled")),
                )
            )
            row = await session.scalar(
                select(FeishuMessageRecord)
                .where(
                    FeishuMessageRecord.status.in_(("queued", "processing")),
                    or_(
                        FeishuMessageRecord.lease_until.is_(None),
                        FeishuMessageRecord.lease_until < now,
                    ),
                )
                .order_by(FeishuMessageRecord.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return False
            if row.attempts >= 3:
                row.status = "failed"
                row.question, row.reply = "", None
                return True
            token = uuid4()
            row.attempts += 1
            row.claim_token, row.status, row.lease_until = (
                token,
                "processing",
                now + timedelta(seconds=120),
            )
            mid, uid, generation, question, month, reply = (
                row.id,
                row.user_id,
                row.binding_generation,
                row.question,
                row.month,
                row.reply,
            )
        try:
            async with self.factory() as session:
                binding = await session.get(FeishuBindingRecord, uid)
                valid = self.valid_binding(binding, generation)
            if not valid:
                await self.finish(mid, token, "cancelled")
                return True
            if reply is None:
                identity = uuid5(
                    NAMESPACE_URL, f"bankpilot:feishu:{self.settings.feishu_app_id}:{mid}"
                )
                try:
                    turn = await ConversationService(self.factory, self.settings).submit(
                        uid,
                        TurnInput(
                            protocol_version=5,
                            expected_context_version=0,
                            request_id=identity,
                            creation_id=identity,
                            question=question,
                            month=month,
                        ),
                        self.gateway,
                    )
                    if turn.status == "processing":
                        raise PlanningError("feishu_turn_pending", 503)
                    reply = str(
                        (turn.reply or {}).get("text")
                        or "本次查询未完成，请在网页助手历史查看后重试。"
                    )
                    if (turn.reply or {}).get("action"):
                        reply += "\n预算提案需要登录网页助手历史确认。"
                except PlanningError as exc:
                    if exc.code == "feishu_turn_pending":
                        raise
                    reply = "本次查询未完成，请登录 BankPilot 查看助手历史或稍后重试。"
                async with self.factory.begin() as session:
                    current = await session.get(FeishuMessageRecord, mid, with_for_update=True)
                    if current is None or current.claim_token != token:
                        return True
                    current.reply = reply
            # Lock binding across delivery: unlink cannot return while an old reply can still start.
            async with self.factory.begin() as session:
                binding = await session.get(FeishuBindingRecord, uid, with_for_update=True)
                current = await session.get(FeishuMessageRecord, mid, with_for_update=True)
                if current is None or current.claim_token != token:
                    return True
                if not self.valid_binding(binding, generation):
                    current.status = "cancelled"
                else:
                    assert binding is not None and binding.open_id is not None
                    await self.adapter.send(binding.open_id, reply, str(uuid5(NAMESPACE_URL, mid)))
                    current.status = "sent"
                current.question, current.reply = "", None
        except asyncio.CancelledError:
            raise
        except Exception:
            # No payloads, keys or provider exception strings in logs. Lease enables recovery.
            logger.warning("Feishu message processing deferred")
        return True

    def valid_binding(self, binding: FeishuBindingRecord | None, generation: UUID) -> bool:
        return bool(
            binding
            and binding.generation == generation
            and binding.open_id
            and binding.app_id == self.settings.feishu_app_id
            and binding.tenant_key == self.settings.feishu_tenant_key
        )

    async def finish(self, mid: str, token: UUID, status: str) -> None:
        async with self.factory.begin() as session:
            row = await session.get(FeishuMessageRecord, mid, with_for_update=True)
            if row and row.claim_token == token:
                row.status, row.question, row.reply = status, "", None

    async def run(self) -> None:
        while True:
            try:
                worked = await self.process_one()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Feishu inbox unavailable")
                worked = False
            await asyncio.sleep(0.2 if worked else 2)


async def order_view(
    row: AlipayOrderRecord, adapter: AlipaySandbox, checkout: bool = False
) -> SandboxOrderView:
    return SandboxOrderView(
        id=row.id,
        subject=row.subject,
        amount=row.amount,
        status=row.status,
        created_at=row.created_at,
        expires_at=row.expires_at,
        checked_at=row.checked_at,
        checkout_url=await sdk_work(lambda: adapter.checkout(row))
        if checkout and row.status == "WAIT_BUYER_PAY" and row.expires_at > datetime.now(UTC)
        else None,
    )


async def create_order(
    session: AsyncSession, settings: Settings, uid: UUID, payload: SandboxPaymentInput
) -> AlipayOrderRecord:
    await lock_owner(session, uid)
    now = await limited(session, settings, uid, "alipay_create")
    row = await session.scalar(
        select(AlipayOrderRecord).where(
            AlipayOrderRecord.user_id == uid, AlipayOrderRecord.operation_id == payload.operation_id
        )
    )
    if row:
        if (
            row.amount != payload.amount
            or row.subject != payload.subject
            or row.app_id != settings.alipay_app_id
            or row.seller_id != settings.alipay_seller_id
        ):
            raise PlanningError("alipay_operation_conflict", 409)
        return row
    row = AlipayOrderRecord(
        user_id=uid,
        operation_id=payload.operation_id,
        app_id=settings.alipay_app_id,
        seller_id=settings.alipay_seller_id,
        subject=payload.subject,
        amount=payload.amount,
        expires_at=now + timedelta(minutes=15),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


def apply_payment(
    row: AlipayOrderRecord, data: dict[str, Any], settings: Settings, *, notification: bool
) -> None:
    try:
        amount = Decimal(str(data["total_amount"]))
        if (
            not amount.is_finite()
            or amount != row.amount
            or data["out_trade_no"] != row.id.hex
            or row.app_id != settings.alipay_app_id
            or row.seller_id != settings.alipay_seller_id
        ):
            raise ValueError("order mismatch")
        if notification and (
            data.get("app_id") != row.app_id or data.get("seller_id") != row.seller_id
        ):
            raise ValueError("merchant mismatch")
        status, trade_no = data["trade_status"], data["trade_no"]
        if (
            status not in {"WAIT_BUYER_PAY", "TRADE_SUCCESS", "TRADE_FINISHED", "TRADE_CLOSED"}
            or not isinstance(trade_no, str)
            or not 1 <= len(trade_no) <= 128
        ):
            raise ValueError("status")
        if row.trade_no and row.trade_no != trade_no:
            raise ValueError("trade mismatch")
        # CLOSED also means a full refund after payment. CLOSED and FINISHED are
        # terminal branches: delayed payment notifications/queries cannot reopen
        # a refunded order, and an old waiting state cannot undo a payment.
        if row.status not in {"TRADE_CLOSED", "TRADE_FINISHED"} and (
            row.status == "WAIT_BUYER_PAY" or status != "WAIT_BUYER_PAY"
        ):
            row.status = status
        row.trade_no, row.checked_at = trade_no, datetime.now(UTC)
    except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
        raise PlanningError("alipay_order_mismatch", 409) from exc
