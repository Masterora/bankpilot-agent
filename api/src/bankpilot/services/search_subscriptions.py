"""Persistent opt-in query watches, calculated without model calls or revision broadcasts."""

import asyncio
import hashlib
import json
import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.config import Settings
from bankpilot.db.assistant_repository import conversation_record, lock_owner
from bankpilot.db.models import AssistantConversationRecord, UserRecord
from bankpilot.domain.assistant import SearchSubscriptionInput
from bankpilot.domain.transaction_search import SEARCH_VERSION, SearchFilters
from bankpilot.errors import PlanningError
from bankpilot.services.transaction_search import attach_relations, matching_items


def clear_subscription(row: AssistantConversationRecord) -> None:
    row.search_subscribed = False
    row.search_fingerprint = None
    row.search_checked_at = None
    row.search_changed_at = None
    row.search_check_error = None
    row.search_subscription_epoch = None


async def fingerprint(session: AsyncSession, uid: UUID, filters: SearchFilters) -> str:
    items = await matching_items(session, uid, filters)
    await attach_relations(session, uid, items)
    encoded = json.dumps(
        {
            "version": SEARCH_VERSION,
            "items": [
                item.model_dump(mode="json")
                for item in sorted(items, key=lambda item: str(item.id))
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


async def set_subscription(
    session: AsyncSession,
    uid: UUID,
    cid: UUID,
    payload: SearchSubscriptionInput,
    settings: Settings,
) -> AssistantConversationRecord:
    await lock_owner(session, uid)
    row = await conversation_record(session, uid, cid, lock=True)
    if row.context_version != payload.expected_context_version:
        raise PlanningError("assistant_context_stale", 409)
    if not payload.enabled:
        clear_subscription(row)
    else:
        if not settings.notifications_enabled:
            raise PlanningError("notifications_disabled", 409)
        if not row.search_context:
            raise PlanningError("search_subscription_filters_required", 422)
        count = await session.scalar(
            select(func.count())
            .select_from(AssistantConversationRecord)
            .where(
                AssistantConversationRecord.user_id == uid,
                AssistantConversationRecord.search_subscribed.is_(True),
                AssistantConversationRecord.deleted.is_(False),
                AssistantConversationRecord.id != cid,
            )
        )
        if count is not None and count >= 20:
            raise PlanningError("search_subscription_limit", 422)
        if not row.search_subscribed:
            row.search_fingerprint = await fingerprint(
                session, uid, SearchFilters.model_validate(row.search_context)
            )
            row.search_checked_at = await session.scalar(select(func.clock_timestamp()))
            row.search_subscription_epoch = settings.notification_epoch
            row.search_changed_at = None
            row.search_check_error = None
        row.search_subscribed = True
    row.context_version += 1
    return row


async def acknowledge(session: AsyncSession, uid: UUID, cid: UUID, changed_at: str) -> None:
    await lock_owner(session, uid)
    row = await conversation_record(session, uid, cid, lock=True)
    if row.search_changed_at and row.search_changed_at.isoformat() != changed_at:
        raise PlanningError("search_subscription_stale", 409)
    row.search_changed_at = None


class SearchSubscriptionProcessor:
    def __init__(self, factory: async_sessionmaker[AsyncSession], settings: Settings):
        self.factory = factory
        self.settings = settings

    async def scan(self) -> None:
        if not self.settings.notifications_enabled:
            return
        async with self.factory() as session:
            targets = (
                await session.execute(
                    select(AssistantConversationRecord.user_id, AssistantConversationRecord.id)
                    .where(
                        AssistantConversationRecord.search_subscribed.is_(True),
                        AssistantConversationRecord.deleted.is_(False),
                        (
                            AssistantConversationRecord.search_checked_at.is_(None)
                            | (
                                AssistantConversationRecord.search_checked_at
                                < func.clock_timestamp() - timedelta(seconds=60)
                            )
                        ),
                    )
                    .order_by(
                        AssistantConversationRecord.search_checked_at.asc().nullsfirst(),
                        AssistantConversationRecord.id,
                    )
                    .limit(20)
                )
            ).all()
        for uid, cid in targets:
            async with asyncio.timeout(10):
                async with self.factory() as session, session.begin():
                    owner = await session.scalar(
                        select(UserRecord.id)
                        .where(UserRecord.id == uid)
                        .with_for_update(skip_locked=True)
                    )
                    if owner is None:
                        continue
                    row = await session.scalar(
                        select(AssistantConversationRecord)
                        .where(
                            AssistantConversationRecord.id == cid,
                            AssistantConversationRecord.user_id == uid,
                            AssistantConversationRecord.deleted.is_(False),
                            AssistantConversationRecord.search_subscribed.is_(True),
                        )
                        .with_for_update()
                    )
                    if row is None:
                        continue
                    now = (await session.execute(select(func.clock_timestamp()))).scalar_one()
                    if row.search_checked_at and row.search_checked_at > now - timedelta(
                        seconds=60
                    ):
                        continue
                    try:
                        current = await fingerprint(
                            session, uid, SearchFilters.model_validate(row.search_context)
                        )
                    except PlanningError as exc:
                        row.search_check_error = exc.code
                    else:
                        if row.search_subscription_epoch != self.settings.notification_epoch:
                            row.search_changed_at = None
                        elif row.search_fingerprint and current != row.search_fingerprint:
                            row.search_changed_at = now
                        row.search_fingerprint = current
                        row.search_subscription_epoch = self.settings.notification_epoch
                        row.search_check_error = None
                    row.search_checked_at = now

    async def run(self) -> None:
        while True:
            try:
                await self.scan()
            except Exception:
                logging.getLogger("uvicorn.error").warning("Search subscription scan unavailable")
            await asyncio.sleep(5)
