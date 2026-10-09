"""Create a user and its notification baseline in the caller's transaction."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.config import Settings
from bankpilot.db.models import UserRecord
from bankpilot.db.user_repository import UserRepository
from bankpilot.services.notifications import schedule_for


async def register_user(
    session: AsyncSession, *, email: str, password_hash: str, settings: Settings
) -> UserRecord:
    user = await UserRepository(session).add(email=email, password_hash=password_hash)
    now = datetime.now(UTC)
    schedule = await schedule_for(session, user.id, now)
    if settings.notifications_enabled:
        schedule.baseline_epoch = settings.notification_epoch
        schedule.initialized_at = now
        schedule.last_reconciled_at = now
    return user
