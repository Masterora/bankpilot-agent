"""User-scoped persistence for discovery decisions and operation receipts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import (
    RecurringDiscoveryDecisionRecord,
    RecurringDiscoveryOperationRecord,
    RecurringDiscoveryProposalRecord,
)


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

    async def proposal_by_request(
        self, user_id: UUID, request_id: UUID
    ) -> RecurringDiscoveryProposalRecord | None:
        return (
            await self.session.scalars(
                select(RecurringDiscoveryProposalRecord).where(
                    RecurringDiscoveryProposalRecord.user_id == user_id,
                    RecurringDiscoveryProposalRecord.proposal_request_id == request_id,
                )
            )
        ).one_or_none()

    async def proposal(
        self, user_id: UUID, proposal_id: UUID
    ) -> RecurringDiscoveryProposalRecord | None:
        return (
            await self.session.scalars(
                select(RecurringDiscoveryProposalRecord).where(
                    RecurringDiscoveryProposalRecord.user_id == user_id,
                    RecurringDiscoveryProposalRecord.id == proposal_id,
                )
            )
        ).one_or_none()

    async def compact_expired_proposals(self, user_id: UUID, now: datetime) -> None:
        await self.session.execute(
            update(RecurringDiscoveryProposalRecord)
            .where(
                RecurringDiscoveryProposalRecord.user_id == user_id,
                RecurringDiscoveryProposalRecord.status == "pending",
                RecurringDiscoveryProposalRecord.expires_at <= now,
            )
            .values(status="expired", draft={}, evidence=[])
        )

    async def pending_proposal_count(self, user_id: UUID) -> int:
        return int(await self.session.scalar(
            select(func.count()).select_from(RecurringDiscoveryProposalRecord).where(
                RecurringDiscoveryProposalRecord.user_id == user_id,
                RecurringDiscoveryProposalRecord.status == "pending",
            )
        ) or 0)

    def add(
        self,
        row: RecurringDiscoveryDecisionRecord
        | RecurringDiscoveryOperationRecord
        | RecurringDiscoveryProposalRecord,
    ) -> None:
        self.session.add(row)
