"""Database-only leases, retries and scans; never invokes models or external delivery."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.db.attention_repository import _next_month
from bankpilot.db.models import (
    NotificationOutboxRecord,
    NotificationRecord,
    NotificationScheduleRecord,
    UserRecord,
)
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.attention import BUSINESS_ZONE
from bankpilot.observability import job_timing
from bankpilot.services.attention import synchronize_existing_states
from bankpilot.services.notifications import baseline, settings_for, valid_event, visibility

logger = logging.getLogger("uvicorn.error")
LEASE = timedelta(seconds=90)
MAX_ATTEMPTS = 5
PROCESS_TIMEOUT = 45


class NotificationProcessor:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def bootstrap(self) -> None:
        now = datetime.now(UTC)
        async with self.factory() as session, session.begin():
            settings = settings_for(session)
            if not settings.notifications_enabled:
                return
            await session.execute(
                insert(NotificationScheduleRecord)
                .from_select(
                    ["user_id", "next_check_at", "attempts"],
                    select(UserRecord.id, literal(now), literal(0)),
                )
                .on_conflict_do_nothing(index_elements=["user_id"])
            )
            await session.execute(
                update(NotificationScheduleRecord)
                .where(or_(
                    NotificationScheduleRecord.baseline_epoch.is_(None),
                    NotificationScheduleRecord.baseline_epoch != settings.notification_epoch,
                ))
                .values(next_check_at=now)
            )

    async def claim(self, scanning: bool) -> tuple[UUID, UUID, UUID] | None:
        now = datetime.now(UTC)
        async with self.factory() as session, session.begin():
            if scanning:
                row = await session.scalar(
                    select(NotificationScheduleRecord)
                    .where(
                        NotificationScheduleRecord.next_check_at <= now,
                        or_(
                            NotificationScheduleRecord.lease_until.is_(None),
                            NotificationScheduleRecord.lease_until <= now,
                        ),
                    )
                    .order_by(NotificationScheduleRecord.next_check_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if row is None:
                    return None
                token = uuid4()
                row.claim_token, row.lease_until = token, now + LEASE
                return row.user_id, row.user_id, token
            event = await session.scalar(
                select(NotificationOutboxRecord)
                .where(
                    or_(
                        (NotificationOutboxRecord.status == "pending")
                        & (NotificationOutboxRecord.available_at <= now),
                        (NotificationOutboxRecord.status == "running")
                        & (NotificationOutboxRecord.lease_until <= now),
                    ),
                )
                .order_by(NotificationOutboxRecord.available_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if event is None:
                return None
            if event.attempts >= MAX_ATTEMPTS:
                event.status = "failed"
                event.error_code = "notification_attempts_exhausted"
                event.claim_token = None
                event.lease_until = None
                return None
            token = uuid4()
            event.claim_token, event.lease_until, event.status = token, now + LEASE, "running"
            event.attempts += 1
            return event.id, event.user_id, token

    async def process(self, claim: tuple[UUID, UUID, UUID], scanning: bool) -> None:
        identity, _, token = claim
        with job_timing(str(token if scanning else identity)):
            async with asyncio.timeout(PROCESS_TIMEOUT) as budget:
                await self._process(claim, scanning, budget)

    async def _process(
        self, claim: tuple[UUID, UUID, UUID], scanning: bool, budget: asyncio.Timeout
    ) -> None:
        identity, uid, token = claim
        completed: dict[str, str | int | float] = {}
        async with self.factory() as session, session.begin():
            await UserRepository(session).lock(uid)
            if scanning:
                schedule = await session.get(
                    NotificationScheduleRecord, identity, with_for_update=True
                )
                now = datetime.now(UTC)
                if (
                    schedule is None
                    or schedule.claim_token != token
                    or not schedule.lease_until
                    or schedule.lease_until <= now
                ):
                    return
                remaining = (schedule.lease_until - now).total_seconds()
                budget.reschedule(
                    min(
                        budget.when() or float("inf"), asyncio.get_running_loop().time() + remaining
                    )
                )
                settings = settings_for(session)
                scan_lag_ms = max(0, (now - schedule.next_check_at).total_seconds() * 1000)
                if schedule.baseline_epoch != settings.notification_epoch:
                    await baseline(session, uid, now)
                else:
                    month = now.astimezone(BUSINESS_ZONE).date().replace(day=1)
                    await synchronize_existing_states(
                        session, uid, now, months={month, _next_month(month)}
                    )
                    schedule.last_reconciled_at = now
                lease_until = schedule.lease_until
                schedule.claim_token = None
                schedule.lease_until = None
                schedule.attempts = 0
                completed = {
                    "event": "notification_scan_completed",
                    "job_id": str(token),
                    "scan_lag_ms": round(scan_lag_ms, 2),
                }
            else:
                event = await session.get(NotificationOutboxRecord, identity, with_for_update=True)
                now = datetime.now(UTC)
                if (
                    event is None
                    or event.status != "running"
                    or event.claim_token != token
                    or not event.lease_until
                    or event.lease_until <= now
                ):
                    return
                remaining = (event.lease_until - now).total_seconds()
                budget.reschedule(
                    min(
                        budget.when() or float("inf"), asyncio.get_running_loop().time() + remaining
                    )
                )
                schedule = await session.get(NotificationScheduleRecord, uid)
                facts, states, disabled, _ = await visibility(session, uid, now)
                valid = bool(
                    schedule
                    and schedule.baseline_epoch == settings_for(session).notification_epoch
                    and valid_event(event, facts, states, disabled, now)
                )
                if valid:
                    await session.execute(
                        insert(NotificationRecord)
                        .values(
                            id=uuid4(),
                            user_id=uid,
                            event_id=event.id,
                            created_at=now,
                        )
                        .on_conflict_do_nothing(index_elements=["event_id"])
                    )
                lease_until = event.lease_until
                event.status = "processed" if valid else "suppressed"
                event.error_code = None if valid else "attention_no_longer_visible"
                event.claim_token = None
                event.lease_until = None
                completed = {
                    "event": "notification_event_completed",
                    "job_id": str(identity),
                    "status": event.status,
                    "event_age_ms": round((now - event.occurred_at).total_seconds() * 1000, 2),
                    "attempts": event.attempts,
                }
            # Flush may wait on other rows too. Expiry must roll back all work, not
            # return normally after materializing a notification or clearing a lease.
            await session.flush()
            if datetime.now(UTC) >= lease_until:
                raise TimeoutError("notification_lease_expired")
        logger.info(json.dumps(completed))

    async def fail(self, claim: tuple[UUID, UUID, UUID], scanning: bool) -> None:
        identity, _, token = claim
        now = datetime.now(UTC)
        async with self.factory() as session, session.begin():
            if scanning:
                schedule = await session.get(
                    NotificationScheduleRecord, identity, with_for_update=True
                )
                if schedule is None or schedule.claim_token != token:
                    return
                schedule.claim_token, schedule.lease_until = None, None
                schedule.attempts += 1
                schedule.next_check_at = now + timedelta(
                    seconds=min(900, 2 ** min(schedule.attempts, 10))
                )
            else:
                event = await session.get(NotificationOutboxRecord, identity, with_for_update=True)
                if event is None or event.claim_token != token:
                    return
                event.claim_token, event.lease_until = None, None
                event.status = "failed" if event.attempts >= MAX_ATTEMPTS else "pending"
                event.error_code = "notification_processing_failed"
                event.available_at = now + timedelta(seconds=min(900, 2 ** min(event.attempts, 10)))
        logger.warning(
            json.dumps(
                {
                    "event": "notification_processing_failed",
                    "job_id": str(token if scanning else identity),
                    "scanning": scanning,
                }
            )
        )

    async def tick(self) -> bool:
        for scanning in (True, False):
            claim = await self.claim(scanning)
            if claim:
                try:
                    await self.process(claim, scanning)
                except Exception:
                    await self.fail(claim, scanning)
                return True
        return False

    async def run(self) -> None:
        while True:
            try:
                if not await self.tick():
                    await asyncio.sleep(5)
            except (SQLAlchemyError, TimeoutError, OSError):
                logger.warning(json.dumps({"event": "notification_worker_unavailable"}))
                await asyncio.sleep(5)
