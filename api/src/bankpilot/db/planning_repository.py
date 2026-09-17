"""文件职责：规划数据的查询与持久化；不执行业务校验、不隐式提交。"""

from datetime import date
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import (
    AccountRecord,
    BudgetRecord,
    RecurringMatchRecord,
    RecurringRecord,
    RecurringRevisionRecord,
    RecurringSkipRecord,
    TransactionCategoryOverrideRecord,
    TransactionRecord,
    TransactionRelationRecord,
)
from bankpilot.domain.reports import month_period


class PlanningRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def budgets(self, user_id: UUID, month: date) -> list[BudgetRecord]:
        return list(
            await self.session.scalars(
                select(BudgetRecord)
                .where(
                    BudgetRecord.user_id == user_id,
                    BudgetRecord.month == month,
                )
                .order_by(BudgetRecord.currency, BudgetRecord.category)
            )
        )

    async def plans(self, user_id: UUID) -> list[RecurringRecord]:
        return list(
            await self.session.scalars(
                select(RecurringRecord)
                .where(
                    RecurringRecord.user_id == user_id,
                )
                .order_by(RecurringRecord.start_date, RecurringRecord.id)
            )
        )

    async def revisions(self, user_id: UUID) -> list[RecurringRevisionRecord]:
        return list(
            await self.session.scalars(
                select(RecurringRevisionRecord)
                .join(RecurringRecord, RecurringRecord.id == RecurringRevisionRecord.plan_id)
                .where(RecurringRecord.user_id == user_id)
                .order_by(RecurringRevisionRecord.effective_month)
            )
        )

    async def matches(self, user_id: UUID, month: date) -> list[RecurringMatchRecord]:
        start, end = month_period(month)
        return list(
            await self.session.scalars(
                select(RecurringMatchRecord)
                .join(
                    RecurringRecord,
                    RecurringRecord.id == RecurringMatchRecord.plan_id,
                )
                .where(
                    RecurringRecord.user_id == user_id,
                    RecurringMatchRecord.due_date.between(start, end),
                )
            )
        )

    async def skips(self, user_id: UUID, month: date) -> list[RecurringSkipRecord]:
        return list(
            await self.session.scalars(
                select(RecurringSkipRecord)
                .join(RecurringRecord, RecurringRecord.id == RecurringSkipRecord.plan_id)
                .where(
                    RecurringRecord.user_id == user_id,
                    RecurringSkipRecord.due_date.between(*month_period(month)),
                )
            )
        )

    async def transactions(
        self,
        user_id: UUID,
        *,
        month: date | None = None,
        ids: set[UUID] | None = None,
    ) -> list[tuple[TransactionRecord, str, str | None]]:
        statement = (
            select(
                TransactionRecord,
                AccountRecord.name,
                TransactionCategoryOverrideRecord.category,
            )
            .join(AccountRecord)
            .outerjoin(
                TransactionCategoryOverrideRecord,
                (TransactionCategoryOverrideRecord.transaction_id == TransactionRecord.id)
                & (TransactionCategoryOverrideRecord.user_id == user_id),
            )
            .where(AccountRecord.user_id == user_id)
        )
        if month is not None:
            statement = statement.where(
                TransactionRecord.booking_date.between(*month_period(month))
            )
        if ids is not None:
            statement = statement.where(TransactionRecord.id.in_(ids))
        return list(
            (
                await self.session.execute(
                    statement.order_by(
                        TransactionRecord.booking_date,
                        TransactionRecord.id,
                    ).limit(10_001)
                )
            ).tuples()
        )

    async def relations(
        self,
        user_id: UUID,
        ids: set[UUID],
    ) -> list[TransactionRelationRecord]:
        return list(
            await self.session.scalars(
                select(TransactionRelationRecord).where(
                    TransactionRelationRecord.user_id == user_id,
                    TransactionRelationRecord.state == "confirmed",
                    or_(
                        TransactionRelationRecord.first_id.in_(ids),
                        TransactionRelationRecord.second_id.in_(ids),
                    ),
                )
            )
        )

    async def linked_ids(self, user_id: UUID, ids: set[UUID]) -> set[UUID]:
        return set(
            await self.session.scalars(
                select(RecurringMatchRecord.transaction_id)
                .join(
                    RecurringRecord,
                    RecurringRecord.id == RecurringMatchRecord.plan_id,
                )
                .where(
                    RecurringRecord.user_id == user_id, RecurringMatchRecord.transaction_id.in_(ids)
                )
            )
        )

    async def budget(
        self, user_id: UUID, month: date, category: str, currency: str
    ) -> BudgetRecord | None:
        return await self.session.get(BudgetRecord, (user_id, month, category, currency))

    async def account(self, user_id: UUID, identity: UUID) -> AccountRecord | None:
        record: AccountRecord | None = await self.session.scalar(
            select(AccountRecord).where(
                AccountRecord.id == identity,
                AccountRecord.user_id == user_id,
            )
        )
        return record

    async def plan(self, user_id: UUID, identity: UUID) -> RecurringRecord | None:
        record: RecurringRecord | None = await self.session.scalar(
            select(RecurringRecord).where(
                RecurringRecord.id == identity,
                RecurringRecord.user_id == user_id,
            )
        )
        return record

    async def creation_identity(self, identity: UUID) -> RecurringRecord | None:
        """仅供创建去重；服务必须校验返回记录归属，不能用于工作区读取。"""
        return await self.session.get(RecurringRecord, identity)

    async def revision(self, identity: UUID, month: date) -> RecurringRevisionRecord | None:
        """调用方先取得并锁定所属用户的计划，再读取子记录。"""
        return await self.session.get(RecurringRevisionRecord, (identity, month))

    async def match(self, identity: UUID, due: date) -> RecurringMatchRecord | None:
        return await self.session.get(RecurringMatchRecord, (identity, due))

    async def skip(self, identity: UUID, due: date) -> RecurringSkipRecord | None:
        return await self.session.get(RecurringSkipRecord, (identity, due))

    async def remove_match(self, identity: UUID, due: date) -> None:
        await self.session.execute(
            delete(RecurringMatchRecord).where(
                RecurringMatchRecord.plan_id == identity,
                RecurringMatchRecord.due_date == due,
            )
        )

    async def last_reviewed_date(self, identity: UUID) -> date | None:
        dates = [
            await self.session.scalar(
                select(func.max(record.due_date)).where(record.plan_id == identity)
            )
            for record in (RecurringMatchRecord, RecurringSkipRecord)
        ]
        return max((value for value in dates if value is not None), default=None)

    def add(
        self,
        record: BudgetRecord
        | RecurringRecord
        | RecurringRevisionRecord
        | RecurringMatchRecord
        | RecurringSkipRecord,
    ) -> None:
        self.session.add(record)

    async def remove(
        self, record: BudgetRecord | RecurringRevisionRecord | RecurringSkipRecord
    ) -> None:
        await self.session.delete(record)
