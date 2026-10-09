"""Transactional notification projection; all facts and permissions remain deterministic."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.config import Settings, get_settings
from bankpilot.db.attention_repository import AttentionRepository, _next_month
from bankpilot.db.models import (
    AssistantConversationRecord,
    AttentionStateRecord,
    NotificationOutboxRecord,
    NotificationRecord,
    NotificationScheduleRecord,
)
from bankpilot.domain.attention import BUSINESS_ZONE, AttentionFact, AttentionState, AttentionType
from bankpilot.domain.transaction_search import SearchFilters
from bankpilot.errors import PlanningError


class NotificationItem(BaseModel):
    id: UUID
    attention_type: AttentionType
    source_type: Literal["budget", "recurring"]
    source_id: UUID
    source_date: date
    title: str
    created_at: datetime
    seen_at: datetime | None


class QueryChange(BaseModel):
    conversation_id: UUID
    title: str
    filters: SearchFilters
    changed_at: datetime


class NotificationPage(BaseModel):
    query_changes: list[QueryChange] = Field(default_factory=list)
    items: list[NotificationItem]
    server_time: datetime
    count_status: Literal["ready", "incomplete"]
    unseen_count: int | None
    next_cursor: str | None


def settings_for(session: AsyncSession) -> Settings:
    value = session.info.get("notification_settings")
    return value if isinstance(value, Settings) else get_settings()


def in_window(fact: AttentionFact, now: datetime) -> bool:
    today = now.astimezone(BUSINESS_ZONE).date()
    if not fact.active:
        return False
    if fact.source_type == "budget":
        return fact.source_date == today.replace(day=1)
    if fact.attention_type == AttentionType.RECURRING_UPCOMING:
        return 1 <= (fact.source_date - today).days <= 7
    return fact.source_date <= today and fact.source_date.replace(day=1) == today.replace(day=1)


async def schedule_for(
    session: AsyncSession, uid: UUID, now: datetime
) -> NotificationScheduleRecord:
    row = await session.get(NotificationScheduleRecord, uid)
    if row is None:
        row = NotificationScheduleRecord(user_id=uid, next_check_at=now, attempts=0)
        session.add(row)
        await session.flush()
    return row


async def record_transition(
    session: AsyncSession,
    row: AttentionStateRecord,
    before: AttentionState | None,
    fact: AttentionFact,
    now: datetime,
    *,
    emit: bool,
    entered: bool = False,
) -> None:
    settings = settings_for(session)
    if not settings.notifications_enabled:
        return
    schedule = await schedule_for(session, row.user_id, now)
    if (
        not emit
        or schedule.baseline_epoch != settings.notification_epoch
        or not in_window(fact, now)
    ):
        return
    opened = entered or before is None or row.generation != before.generation
    expired = before is not None and before.state == "snoozed" and row.state == "unread"
    if not opened and not expired:
        return
    preference = await AttentionRepository(session).preference(row.user_id, row.attention_type)
    if row.state != "unread" or (preference is not None and not preference.enabled):
        return
    session.add(
        NotificationOutboxRecord(
            user_id=row.user_id,
            source_type=row.source_type,
            source_id=row.source_id,
            source_date=row.source_date,
            generation=row.generation,
            state_revision=row.revision,
            attention_type=row.attention_type,
            event_type="attention.opened" if opened else "attention.snooze_due",
            occurred_at=now,
            available_at=now,
        )
    )


async def current_facts(
    session: AsyncSession, uid: UUID, now: datetime
) -> tuple[dict[tuple[str, UUID, date], AttentionFact], bool]:
    from bankpilot.services.attention import facts_for_group

    month = now.astimezone(BUSINESS_ZONE).date().replace(day=1)
    result: dict[tuple[str, UUID, date], AttentionFact] = {}
    complete = True
    for kind, target in (
        ("budget", month),
        ("recurring", month),
        ("recurring", _next_month(month)),
    ):
        try:
            facts = await facts_for_group(session, uid, target, kind, now)
        except PlanningError as exc:
            if exc.code != "planning_period_limit":
                raise
            complete = False
            continue
        result.update({(kind, fact.source_id, fact.source_date): fact for fact in facts.values()})
    return result, complete


async def visibility(
    session: AsyncSession, uid: UUID, now: datetime
) -> tuple[
    dict[tuple[str, UUID, date], AttentionFact],
    dict[tuple[str, UUID, date], AttentionStateRecord],
    set[str],
    bool,
]:
    facts, complete = await current_facts(session, uid, now)
    month = now.astimezone(BUSINESS_ZONE).date().replace(day=1)
    rows = await AttentionRepository(session).states(uid, months={month, _next_month(month)})
    states = {(r.source_type, r.source_id, r.source_date): r for r in rows}
    disabled = {
        r.attention_type
        for r in await AttentionRepository(session).preferences(uid)
        if not r.enabled
    }
    return facts, states, disabled, complete


def valid_event(
    event: NotificationOutboxRecord,
    facts: dict[tuple[str, UUID, date], AttentionFact],
    states: dict[tuple[str, UUID, date], AttentionStateRecord],
    disabled: set[str],
    now: datetime,
) -> bool:
    key = event.source_type, event.source_id, event.source_date
    fact, row = facts.get(key), states.get(key)
    return bool(
        fact
        and row
        and in_window(fact, now)
        and row.fact_status == "active"
        and row.fact_signature == fact.signature
        and str(fact.attention_type) == event.attention_type
        and row.state == "unread"
        and row.generation == event.generation
        and row.revision == event.state_revision
        and row.attention_type == event.attention_type
        and event.attention_type not in disabled
    )


async def invalidate(
    session: AsyncSession, uid: UUID, now: datetime, *, fully_reconciled: bool = False
) -> None:
    """Called under the user lock after writes, with bounded current facts."""
    if not settings_for(session).notifications_enabled:
        return
    await session.flush()
    facts, states, disabled, _ = await visibility(session, uid, now)
    pairs = await session.execute(
        select(NotificationRecord, NotificationOutboxRecord)
        .join(NotificationOutboxRecord, NotificationRecord.event_id == NotificationOutboxRecord.id)
        .where(NotificationRecord.user_id == uid, NotificationRecord.suppressed_at.is_(None))
    )
    for notification, event in pairs:
        if not valid_event(event, facts, states, disabled, now):
            notification.suppressed_at = now
    events = await session.scalars(
        select(NotificationOutboxRecord).where(
            NotificationOutboxRecord.user_id == uid,
            NotificationOutboxRecord.status.in_(("pending", "running")),
        )
    )
    for event in events:
        if not valid_event(event, facts, states, disabled, now):
            event.status = "suppressed"
            event.error_code = "attention_no_longer_visible"
            event.claim_token = None
            event.lease_until = None
    schedule = await schedule_for(session, uid, now)
    # Exact snooze deadlines plus midnight cover window entry, due dates and month changes.
    boundary = datetime.combine(
        now.astimezone(BUSINESS_ZONE).date() + timedelta(days=1), time.min, BUSINESS_ZONE
    ).astimezone(UTC)
    snooze = await AttentionRepository(session).next_notification_snooze(
        uid, now=now, today=now.astimezone(BUSINESS_ZONE).date()
    )
    deadline = min(boundary, snooze) if snooze else boundary
    if fully_reconciled:
        schedule.last_reconciled_at = now
        schedule.next_check_at = deadline
    else:
        # A scoped business write must not erase an overdue scan for unrelated sources.
        schedule.next_check_at = min(schedule.next_check_at, deadline)


async def baseline(session: AsyncSession, uid: UUID, now: datetime) -> bool:
    from bankpilot.services.attention import synchronize_existing_states

    schedule = await schedule_for(session, uid, now)
    month = now.astimezone(BUSINESS_ZONE).date().replace(day=1)
    await synchronize_existing_states(
        session, uid, now, months={month, _next_month(month)}, emit=False
    )
    _, complete = await current_facts(session, uid, now)
    if not complete:
        schedule.baseline_epoch = None
        schedule.next_check_at = now + timedelta(minutes=5)
        return False
    await session.execute(
        update(NotificationOutboxRecord)
        .where(
            NotificationOutboxRecord.user_id == uid,
            NotificationOutboxRecord.status.in_(("pending", "running", "failed")),
        )
        .values(
            status="suppressed", claim_token=None, lease_until=None, error_code="baseline_reset"
        )
    )
    schedule.baseline_epoch = settings_for(session).notification_epoch
    schedule.initialized_at = now
    schedule.last_reconciled_at = now
    return True


def encode_cursor(
    uid: UUID, created: datetime, identity: UUID, depth: int, settings: Settings
) -> str:
    data = json.dumps(
        [str(uid), created.isoformat(), str(identity), depth], separators=(",", ":")
    ).encode()
    signature = hmac.new(
        settings.session_secret.get_secret_value().encode(), data, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(signature + data).decode()


def decode_cursor(value: str, uid: UUID, settings: Settings) -> tuple[datetime, UUID, int]:
    try:
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
        signature, data = raw[:32], raw[32:]
        expected = hmac.new(
            settings.session_secret.get_secret_value().encode(), data, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        owner, timestamp, identity, depth = json.loads(data)
        created = datetime.fromisoformat(timestamp)
        if (
            owner != str(uid)
            or not isinstance(depth, int)
            or not 1 <= depth <= 100
            or created.tzinfo is None
        ):
            raise ValueError
        return created, UUID(identity), depth
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise PlanningError("notification_cursor_invalid", 422) from exc


async def read_page(
    session: AsyncSession, uid: UUID, now: datetime, limit: int, cursor: str | None
) -> NotificationPage:
    settings = settings_for(session)
    facts, states, disabled, complete = await visibility(session, uid, now)
    schedule = await session.get(NotificationScheduleRecord, uid)
    complete = bool(
        complete
        and schedule
        and schedule.baseline_epoch == settings.notification_epoch
        and schedule.last_reconciled_at
        and schedule.next_check_at + timedelta(seconds=60) >= now
    )
    statement = (
        select(NotificationRecord, NotificationOutboxRecord)
        .join(NotificationOutboxRecord, NotificationRecord.event_id == NotificationOutboxRecord.id)
        .where(NotificationRecord.user_id == uid, NotificationRecord.suppressed_at.is_(None))
    )
    # The same repeatable-read snapshot checks every unsuppressed item for the badge.
    all_rows = list((await session.execute(statement.limit(1001))).all())
    complete = complete and len(all_rows) <= 1000
    unseen = 0
    for notification, event in all_rows:
        if not valid_event(event, facts, states, disabled, now):
            complete = False
        elif notification.seen_at is None:
            unseen += 1
    depth = 0
    if cursor:
        created, identity, depth = decode_cursor(cursor, uid, settings)
        statement = statement.where(
            or_(
                NotificationRecord.created_at < created,
                (NotificationRecord.created_at == created) & (NotificationRecord.id < identity),
            )
        )
    rows = list(
        (
            await session.execute(
                statement.order_by(
                    NotificationRecord.created_at.desc(), NotificationRecord.id.desc()
                ).limit(limit + 1)
            )
        ).all()
    )
    items = []
    for notification, event in rows[:limit]:
        if valid_event(event, facts, states, disabled, now):
            fact = facts[(event.source_type, event.source_id, event.source_date)]
            items.append(
                NotificationItem(
                    id=notification.id,
                    attention_type=AttentionType(event.attention_type),
                    source_type=event.source_type,
                    source_id=event.source_id,
                    source_date=event.source_date,
                    title=fact.title,
                    created_at=notification.created_at,
                    seen_at=notification.seen_at,
                )
            )
    next_cursor = None
    if len(rows) > limit and depth >= 100:
        raise PlanningError("notification_page_limit", 422)
    if len(rows) > limit:
        last = rows[limit - 1][0]
        next_cursor = encode_cursor(uid, last.created_at, last.id, depth + 1, settings)
    watches = list(
        (
            await session.scalars(
                select(AssistantConversationRecord)
                .where(
                    AssistantConversationRecord.user_id == uid,
                    AssistantConversationRecord.search_subscribed.is_(True),
                    AssistantConversationRecord.deleted.is_(False),
                )
                .order_by(
                    AssistantConversationRecord.search_changed_at.desc().nullslast(),
                    AssistantConversationRecord.id,
                )
                .limit(21)
            )
        ).all()
    )
    complete = complete and len(watches) <= 20
    query_changes = []
    for watch in watches[:20]:
        if (
            watch.search_check_error
            or not watch.search_checked_at
            or watch.search_checked_at + timedelta(seconds=120) < now
            or watch.search_subscription_epoch != settings.notification_epoch
        ):
            complete = False
        if (
            watch.search_changed_at
            and watch.search_context
            and watch.search_subscription_epoch == settings.notification_epoch
        ):
            query_changes.append(
                QueryChange(
                    conversation_id=watch.id,
                    title=watch.title or "",
                    filters=SearchFilters.model_validate(watch.search_context),
                    changed_at=watch.search_changed_at,
                )
            )
    unseen += len(query_changes)
    return NotificationPage(
        query_changes=query_changes,
        items=items,
        server_time=now,
        count_status="ready" if complete else "incomplete",
        unseen_count=unseen if complete else None,
        next_cursor=next_cursor,
    )
