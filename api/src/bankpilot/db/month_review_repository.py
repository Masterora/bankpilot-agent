"""Owned month declarations; caller owns locks and transaction completion."""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import AccountMonthReviewRecord, AccountRecord


class MonthReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def accounts(self, uid: UUID) -> list[AccountRecord]:
        return list(
            await self.session.scalars(
                select(AccountRecord)
                .where(AccountRecord.user_id == uid)
                .order_by(AccountRecord.name, AccountRecord.id)
            )
        )

    async def records(self, uid: UUID, month: date) -> list[AccountMonthReviewRecord]:
        return list(
            await self.session.scalars(
                select(AccountMonthReviewRecord).where(
                    AccountMonthReviewRecord.user_id == uid, AccountMonthReviewRecord.month == month
                )
            )
        )
