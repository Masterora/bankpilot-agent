"""Authenticated notification inbox; seeing a notification never handles its business source."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import (
    get_app_settings,
    get_current_user,
    get_db_session,
    get_snapshot_session,
    get_snapshot_user,
)
from bankpilot.api.errors import ApiProblem
from bankpilot.config import Settings
from bankpilot.db.models import NotificationRecord, UserRecord
from bankpilot.db.user_repository import UserRepository
from bankpilot.errors import PlanningError
from bankpilot.services.notifications import NotificationPage, read_page

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class Availability(BaseModel):
    enabled: bool


class SeenReceipt(BaseModel):
    id: UUID
    seen_at: datetime


def enabled(settings: Settings) -> None:
    if not settings.notifications_enabled:
        raise ApiProblem(404, "notifications_unavailable")


@router.get("/availability", response_model=Availability)
async def availability(
    settings: Settings = Depends(get_app_settings), user: UserRecord = Depends(get_current_user)
) -> Availability:
    return Availability(enabled=settings.notifications_enabled)


@router.get("", response_model=NotificationPage)
async def inbox(
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
    settings: Settings = Depends(get_app_settings),
) -> NotificationPage:
    enabled(settings)
    try:
        return await read_page(session, user.id, datetime.now(UTC), limit, cursor)
    except PlanningError as exc:
        raise ApiProblem(exc.status, exc.code) from exc


@router.post("/{identity}/seen", response_model=SeenReceipt)
async def seen(
    identity: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> SeenReceipt:
    enabled(settings)
    await UserRepository(session).lock(user.id)
    row = await session.scalar(
        select(NotificationRecord).where(
            NotificationRecord.id == identity, NotificationRecord.user_id == user.id
        )
    )
    if row is None:
        raise ApiProblem(404, "notification_not_found")
    if row.seen_at is None:
        row.seen_at = datetime.now(UTC)
    result = SeenReceipt(id=row.id, seen_at=row.seen_at)
    await session.commit()
    return result
