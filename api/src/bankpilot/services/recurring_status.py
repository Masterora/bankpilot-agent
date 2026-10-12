"""Read status boundaries without changing the legacy fallback or financial ledger."""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import RecurringRecord, RecurringStatusRecord


async def status_changes(session: AsyncSession, uid: UUID) -> list[RecurringStatusRecord]:
    return list(
        await session.scalars(
            select(RecurringStatusRecord)
            .join(RecurringRecord)
            .where(RecurringRecord.user_id == uid)
            .order_by(RecurringStatusRecord.effective_date)
        )
    )


def status_at(plan: RecurringRecord, changes: list[RecurringStatusRecord], day: date) -> str:
    eligible = [r for r in changes if r.plan_id == plan.id and r.effective_date <= day]
    return max(eligible, key=lambda r: r.effective_date).status if eligible else plan.status
