"""User-scoped persistence for discovery decisions and operation receipts."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import RecurringDiscoveryDecisionRecord, RecurringDiscoveryOperationRecord


class DiscoveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def decisions(self, user_id: UUID) -> list[RecurringDiscoveryDecisionRecord]:
        return list(
            await self.session.scalars(
                select(RecurringDiscoveryDecisionRecord).where(
                    RecurringDiscoveryDecisionRecord.user_id == user_id
                )
            )
        )

    async def decision(
        self, user_id: UUID, group_key: str
    ) -> RecurringDiscoveryDecisionRecord | None:
        return await self.session.get(RecurringDiscoveryDecisionRecord, (user_id, group_key))

    async def operation(
        self, user_id: UUID, operation_id: UUID
    ) -> RecurringDiscoveryOperationRecord | None:
        return await self.session.get(RecurringDiscoveryOperationRecord, (user_id, operation_id))

    def add(
        self, row: RecurringDiscoveryDecisionRecord | RecurringDiscoveryOperationRecord
    ) -> None:
        self.session.add(row)
