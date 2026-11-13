"""User-scoped template persistence without commits or financial decisions."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import BudgetTemplateApplicationRecord, BudgetTemplateRecord


class TemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, uid: UUID, tid: UUID) -> BudgetTemplateRecord | None:
        row: BudgetTemplateRecord | None = await self.session.scalar(
            select(BudgetTemplateRecord).where(
                BudgetTemplateRecord.user_id == uid, BudgetTemplateRecord.id == tid
            )
        )

        return row

    async def items(self, uid: UUID) -> list[BudgetTemplateRecord]:
        return list(
            await self.session.scalars(
                select(BudgetTemplateRecord)
                .where(BudgetTemplateRecord.user_id == uid)
                .order_by(BudgetTemplateRecord.name, BudgetTemplateRecord.id)
            )
        )

    async def receipt(
        self, uid: UUID, operation_id: UUID
    ) -> BudgetTemplateApplicationRecord | None:
        return await self.session.get(BudgetTemplateApplicationRecord, (uid, operation_id))
