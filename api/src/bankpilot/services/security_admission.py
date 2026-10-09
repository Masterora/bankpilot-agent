"""Atomic shared admission; no financial or permission decisions are delegated to models."""

import asyncio
import hashlib
import hmac
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from anyio import CancelScope
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.config import Settings
from bankpilot.db.models import (
    AssistantConversationRecord,
    AssistantTurnRecord,
    RunRecord,
    SecurityBudgetRecord,
    SecurityLeaseRecord,
)
from bankpilot.errors import PlanningError

model_user: ContextVar[UUID | None] = ContextVar("model_user", default=None)
LEASE_SECONDS = 90
# Fixed application lock serializes short admission transactions across all API processes.
LOCK_ID = 4986404678001


@contextmanager
def model_identity(uid: UUID) -> Iterator[None]:
    token = model_user.set(uid)
    try:
        yield
    finally:
        model_user.reset(token)


async def locked_now(session: AsyncSession) -> datetime:
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_ID})
    now: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()
    await session.execute(
        delete(SecurityBudgetRecord).where(SecurityBudgetRecord.expires_at <= now)
    )
    await session.execute(delete(SecurityLeaseRecord).where(SecurityLeaseRecord.expires_at <= now))
    return now


def private_key(settings: Settings, value: str) -> str:
    return hmac.new(
        settings.session_secret.get_secret_value().encode(), value.encode(), hashlib.sha256
    ).hexdigest()


async def consume(
    session: AsyncSession,
    settings: Settings,
    now: datetime,
    budgets: list[tuple[str, int, int]],
    seconds: int,
    code: str,
) -> None:
    """Caller holds admission lock; rejected reservations roll back with its transaction."""
    deadline = datetime.fromtimestamp((int(now.timestamp()) // seconds + 1) * seconds, UTC)
    for name, maximum, units in budgets:
        key = private_key(settings, name)
        row = await session.get(SecurityBudgetRecord, key)
        if row is None:
            row = SecurityBudgetRecord(key=key, used=0, expires_at=deadline)
            session.add(row)
        if row.used + units > maximum:
            raise PlanningError(code, 429)
        row.used += units


async def admit_model_job(session: AsyncSession, uid: UUID, settings: Settings) -> None:
    now = await locked_now(session)
    for owner, maximum in ((uid, settings.model_user_active), (None, settings.model_global_active)):
        runs = (
            select(func.count())
            .select_from(RunRecord)
            .where(
                RunRecord.status.in_(("CREATED", "PLANNING", "EXECUTING")),
                RunRecord.updated_at >= now - timedelta(seconds=120),
            )
        )
        turns = (
            select(func.count())
            .select_from(AssistantTurnRecord)
            .join(
                AssistantConversationRecord,
                AssistantConversationRecord.id == AssistantTurnRecord.conversation_id,
            )
            .where(AssistantTurnRecord.status == "processing", AssistantTurnRecord.deadline > now)
        )
        if owner is not None:
            runs = runs.where(RunRecord.user_id == owner)
            turns = turns.where(AssistantConversationRecord.user_id == owner)
        active = int(await session.scalar(runs) or 0) + int(await session.scalar(turns) or 0)
        if active >= maximum:
            raise PlanningError("model_work_limit", 429)
    await consume(
        session,
        settings,
        now,
        [
            (f"jobs:{uid}", settings.model_user_jobs_daily, 1),
            ("jobs:global", settings.model_global_jobs_daily, 1),
        ],
        86400,
        "model_daily_limit",
    )


class SecurityAdmission:
    def __init__(self, factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.factory, self.settings = factory, settings

    async def auth(self, source: str, account: str) -> None:
        async with self.factory.begin() as session:
            now = await locked_now(session)
            await consume(
                session,
                self.settings,
                now,
                [
                    ("auth:global", self.settings.auth_global_per_minute, 1),
                    (f"auth:source:{source}", self.settings.auth_source_per_minute, 1),
                    (
                        f"auth:account:{account.casefold()}",
                        self.settings.auth_account_per_minute,
                        1,
                    ),
                ],
                60,
                "authentication_rate_limit",
            )

    async def reserve(
        self,
        purpose: str,
        subject: str,
        local_limit: int,
        global_limit: int,
        *,
        tokens: int = 0,
    ) -> UUID:
        identity = uuid4()
        async with self.factory.begin() as session:
            now = await locked_now(session)
            private_subject = private_key(self.settings, subject)
            query = (
                select(func.count())
                .select_from(SecurityLeaseRecord)
                .where(SecurityLeaseRecord.purpose == purpose)
            )
            total = int(await session.scalar(query) or 0)
            owned = int(
                await session.scalar(query.where(SecurityLeaseRecord.subject == private_subject))
                or 0
            )
            if total >= global_limit or owned >= local_limit:
                raise PlanningError(f"{purpose}_concurrency_limit", 429)
            if purpose == "model":
                await consume(
                    session,
                    self.settings,
                    now,
                    [
                        (f"attempts:{subject}", self.settings.model_user_attempts_daily, 1),
                        ("attempts:global", self.settings.model_global_attempts_daily, 1),
                        (f"tokens:{subject}", self.settings.model_user_tokens_daily, tokens),
                        ("tokens:global", self.settings.model_global_tokens_daily, tokens),
                    ],
                    86400,
                    "model_daily_limit",
                )
            session.add(
                SecurityLeaseRecord(
                    id=identity,
                    purpose=purpose,
                    subject=private_subject,
                    expires_at=now + timedelta(seconds=LEASE_SECONDS),
                )
            )
        return identity

    async def release(self, identity: UUID) -> None:
        async with self.factory.begin() as session:
            await session.execute(
                delete(SecurityLeaseRecord).where(SecurityLeaseRecord.id == identity)
            )

    async def renew(self, identity: UUID) -> None:
        async with self.factory.begin() as session:
            now: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()
            renewed = await session.scalar(
                update(SecurityLeaseRecord)
                .where(SecurityLeaseRecord.id == identity, SecurityLeaseRecord.expires_at > now)
                .values(expires_at=now + timedelta(seconds=LEASE_SECONDS))
                .returning(SecurityLeaseRecord.id)
            )
            if renewed is None:
                raise PlanningError("security_lease_expired", 503)

    @asynccontextmanager
    async def lease(
        self,
        purpose: str,
        subject: str,
        local_limit: int,
        global_limit: int,
        *,
        tokens: int = 0,
    ) -> AsyncIterator[None]:
        identity = await self.reserve(purpose, subject, local_limit, global_limit, tokens=tokens)
        owner = asyncio.current_task()

        async def heartbeat() -> None:
            try:
                while True:
                    await asyncio.sleep(15)
                    await self.renew(identity)
            except Exception:
                if owner is not None:
                    owner.cancel()

        task = asyncio.create_task(heartbeat())
        try:
            yield
        finally:
            with CancelScope(shield=True):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                await self.release(identity)

    async def register_instance(self, identity: UUID) -> None:
        values = self.settings.model_dump(
            include={
                name
                for name in Settings.model_fields
                if name.startswith(("auth_", "password_", "model_", "stream_", "notification"))
                and name not in {"model_id", "model_provider", "model_base_url"}
            }
        )
        values["admission_secret_digest"] = hashlib.sha256(
            self.settings.session_secret.get_secret_value().encode()
        ).hexdigest()
        fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        async with self.factory.begin() as session:
            now = await locked_now(session)
            mismatch = await session.scalar(
                select(SecurityLeaseRecord.id)
                .where(
                    SecurityLeaseRecord.purpose == "instance",
                    SecurityLeaseRecord.id != identity,
                    SecurityLeaseRecord.configuration != fingerprint,
                )
                .limit(1)
            )
            if mismatch is not None:
                raise RuntimeError("Shared API security/notification settings differ")
            row = await session.get(SecurityLeaseRecord, identity)
            if row is None:
                session.add(
                    SecurityLeaseRecord(
                        id=identity,
                        purpose="instance",
                        subject="api",
                        configuration=fingerprint,
                        expires_at=now + timedelta(seconds=LEASE_SECONDS),
                    )
                )
            else:
                row.expires_at = now + timedelta(seconds=LEASE_SECONDS)
