"""Persistence helpers for user-isolated attention state and operation receipts."""

from datetime import date
from typing import cast
from uuid import UUID

from sqlalchemy import delete, extract, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import (
    AccountRecord,
    AttentionOperationRecord,
    AttentionPreferenceRecord,
    AttentionStateRecord,
    RecurringMatchRecord,
    RecurringRecord,
    TransactionRecord,
    TransactionRelationRecord,
)


class AttentionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def states(
        self,
        user_id: UUID,
        *,
        month: date | None = None,
        source_type: str | None = None,
        months: set[date] | None = None,
        source_id: UUID | None = None,
    ) -> list[AttentionStateRecord]:
        statement = select(AttentionStateRecord).where(AttentionStateRecord.user_id == user_id)
        if month is not None:
            statement = statement.where(
                AttentionStateRecord.source_date >= month,
                AttentionStateRecord.source_date < _next_month(month),
            )
        if source_type is not None:
            statement = statement.where(AttentionStateRecord.source_type == source_type)
        if source_id is not None:
            statement = statement.where(AttentionStateRecord.source_id == source_id)
        if months is not None:
            statement = statement.where(
                tuple_(
                    extract("year", AttentionStateRecord.source_date),
                    extract("month", AttentionStateRecord.source_date),
                ).in_([(day.year, day.month) for day in months])
            )
        return list(
            await self.session.scalars(
                statement.order_by(
                    AttentionStateRecord.source_type,
                    AttentionStateRecord.source_date,
                    AttentionStateRecord.source_id,
                )
            )
        )

    async def state(
        self, user_id: UUID, source_type: str, source_id: UUID, source_date: date
    ) -> AttentionStateRecord | None:
        return cast(
            AttentionStateRecord | None,
            await self.session.scalar(
                select(AttentionStateRecord).where(
                    AttentionStateRecord.user_id == user_id,
                    AttentionStateRecord.source_type == source_type,
                    AttentionStateRecord.source_id == source_id,
                    AttentionStateRecord.source_date == source_date,
                )
            ),
        )

    async def preferences(self, user_id: UUID) -> list[AttentionPreferenceRecord]:
        return list(
            await self.session.scalars(
                select(AttentionPreferenceRecord)
                .where(AttentionPreferenceRecord.user_id == user_id)
                .order_by(AttentionPreferenceRecord.attention_type)
            )
        )

    async def preference(
        self, user_id: UUID, attention_type: str
    ) -> AttentionPreferenceRecord | None:
        return await self.session.get(AttentionPreferenceRecord, (user_id, attention_type))

    async def operation(self, user_id: UUID, operation_id: UUID) -> AttentionOperationRecord | None:
        return await self.session.get(AttentionOperationRecord, (user_id, operation_id))

    async def delete_state(self, state: AttentionStateRecord) -> None:
        await self.session.delete(state)

    async def delete_source(self, user_id: UUID, source_type: str, source_id: UUID) -> None:
        await self.session.execute(
            delete(AttentionStateRecord).where(
                AttentionStateRecord.user_id == user_id,
                AttentionStateRecord.source_type == source_type,
                AttentionStateRecord.source_id == source_id,
            )
        )

    async def affected_months(self, user_id: UUID, transaction_ids: set[UUID]) -> set[date]:
        """Capture dependencies before deletion cascades remove relations and matches."""
        if not transaction_ids:
            return set()
        ids = set(transaction_ids)
        relations = await self.session.scalars(
            select(TransactionRelationRecord).where(
                TransactionRelationRecord.user_id == user_id,
                TransactionRelationRecord.state == "confirmed",
                or_(
                    TransactionRelationRecord.first_id.in_(ids),
                    TransactionRelationRecord.second_id.in_(ids),
                ),
            )
        )
        for relation in relations:
            ids.update((relation.first_id, relation.second_id))
        dates = list(
            await self.session.scalars(
                select(TransactionRecord.booking_date)
                .join(AccountRecord)
                .where(
                    AccountRecord.user_id == user_id,
                    TransactionRecord.id.in_(ids),
                )
            )
        )
        dates.extend(
            await self.session.scalars(
                select(RecurringMatchRecord.due_date)
                .join(RecurringRecord)
                .where(
                    RecurringRecord.user_id == user_id,
                    RecurringMatchRecord.transaction_id.in_(ids),
                )
            )
        )
        return {day.replace(day=1) for day in dates}

    def add(
        self,
        record: AttentionStateRecord | AttentionPreferenceRecord | AttentionOperationRecord,
    ) -> None:
        self.session.add(record)


def _next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)
