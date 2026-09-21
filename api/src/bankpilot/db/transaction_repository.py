"""
文件职责：封装交易查询、搜索候选读取、去重和分类覆盖。
主要内容：按用户读取账本，按日期与账户等条件稳定排序，检测导入冲突、批量写入并保存分类覆盖。
关键边界：不隐式提交；分类写入锁定用户并递增修订号，批量导入的锁与修订号由调用服务统一管理。
"""
from datetime import UTC, date
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import (
    AccountRecord,
    TransactionCategoryOverrideRecord,
    TransactionRecord,
    UserRecord,
)
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.statement_import import ParsedStatementRow
from bankpilot.domain.transaction_search import CAPACITY, SearchFilters
from bankpilot.errors import PlanningError


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def query_for_user(
        self, *, user_id: UUID, start_date: date, end_date: date
    ) -> list[tuple[TransactionRecord, str, str | None]]:
        rows = await self.session.execute(
            select(
                TransactionRecord,
                AccountRecord.name,
                TransactionCategoryOverrideRecord.category,
            )
            .join(AccountRecord, TransactionRecord.account_id == AccountRecord.id)
            .outerjoin(
                TransactionCategoryOverrideRecord,
                and_(
                    TransactionCategoryOverrideRecord.transaction_id == TransactionRecord.id,
                    TransactionCategoryOverrideRecord.user_id == user_id,
                ),
            )
            .where(
                AccountRecord.user_id == user_id,
                TransactionRecord.booking_date >= start_date,
                TransactionRecord.booking_date <= end_date,
            )
            .order_by(TransactionRecord.occurred_at.desc())
        )
        return list(rows.tuples())

    async def search_rows(
        self,
        user_id: UUID,
        filters: SearchFilters | None = None,
        transaction_id: UUID | None = None,
    ) -> list[tuple[TransactionRecord, str, str | None]]:
        query = (
            select(
                TransactionRecord, AccountRecord.name, TransactionCategoryOverrideRecord.category
            )
            .join(AccountRecord, TransactionRecord.account_id == AccountRecord.id)
            .outerjoin(
                TransactionCategoryOverrideRecord,
                and_(
                    TransactionCategoryOverrideRecord.transaction_id == TransactionRecord.id,
                    TransactionCategoryOverrideRecord.user_id == user_id,
                ),
            )
            .where(AccountRecord.user_id == user_id)
        )
        if transaction_id is not None:
            query = query.where(TransactionRecord.id == transaction_id)
        if filters:
            query = query.where(
                TransactionRecord.booking_date >= filters.start_date,
                TransactionRecord.booking_date <= filters.end_date,
            )
            for column, value in (
                (TransactionRecord.account_id, filters.account_id),
                (TransactionRecord.currency, filters.currency),
                (TransactionRecord.import_batch_id, filters.import_batch_id),
            ):
                if value is not None:
                    query = query.where(column == value)
            if filters.direction == "debit":
                query = query.where(TransactionRecord.amount < 0)
            elif filters.direction == "credit":
                query = query.where(TransactionRecord.amount > 0)
            if filters.min_amount is not None:
                query = query.where(
                    func.abs(TransactionRecord.amount) >= Decimal(filters.min_amount)
                )
            if filters.max_amount is not None:
                query = query.where(
                    func.abs(TransactionRecord.amount) <= Decimal(filters.max_amount)
                )
        rows = await self.session.execute(
            query.order_by(
                TransactionRecord.booking_date.desc(),
                TransactionRecord.occurred_at.desc(),
                TransactionRecord.id.asc(),
            ).limit(CAPACITY + 1)
        )
        return list(rows.tuples())

    async def set_category_override(
        self, *, user_id: UUID, transaction_id: UUID, category: str, expected_revision: int
    ) -> TransactionRecord | None:
        revision = await self.session.scalar(
            select(UserRecord.ledger_revision).where(UserRecord.id == user_id).with_for_update()
        )
        if revision != expected_revision:
            raise PlanningError("search_stale", 409)
        transaction = cast(
            TransactionRecord | None,
            await self.session.scalar(
                select(TransactionRecord)
                .join(AccountRecord, TransactionRecord.account_id == AccountRecord.id)
                .where(TransactionRecord.id == transaction_id, AccountRecord.user_id == user_id)
            ),
        )
        if transaction is None:
            return None
        existing = await self.session.get(TransactionCategoryOverrideRecord, transaction_id)
        changed = existing is None or existing.category != category
        if existing is None:
            self.session.add(
                TransactionCategoryOverrideRecord(
                    transaction_id=transaction_id,
                    user_id=user_id,
                    category=category,
                )
            )
        else:
            existing.category = category
        await self.session.flush()
        if changed:
            await UserRepository(self.session).bump_revision(user_id)
        return transaction

    async def existing_fingerprints(self, *, account_id: UUID, fingerprints: set[str]) -> set[str]:
        if not fingerprints:
            return set()
        values = await self.session.scalars(
            select(TransactionRecord.source_fingerprint).where(
                TransactionRecord.account_id == account_id,
                TransactionRecord.source_fingerprint.in_(fingerprints),
            )
        )
        return {value for value in values if value is not None}

    async def conflicting_rows(
        self, *, account_id: UUID, rows: list[ParsedStatementRow]
    ) -> list[int]:
        if not rows:
            return []
        records = await self.session.scalars(
            select(TransactionRecord).where(
                TransactionRecord.account_id == account_id,
                TransactionRecord.source_fingerprint.in_({row.fingerprint for row in rows}),
            )
        )
        existing = {record.source_fingerprint: record for record in records}
        return [
            row.row_number
            for row in rows
            if row.fingerprint in existing
            and (
                existing[row.fingerprint].booking_date != row.booking_date
                or existing[row.fingerprint].occurred_at.replace(tzinfo=UTC) != row.occurred_at
                or existing[row.fingerprint].amount != row.amount
                or existing[row.fingerprint].currency != row.currency
                or existing[row.fingerprint].merchant.casefold() != row.merchant.casefold()
                or existing[row.fingerprint].description.casefold() != row.description.casefold()
            )
        ]

    async def add_imported(
        self,
        *,
        account_id: UUID,
        import_batch_id: UUID,
        rows: list[ParsedStatementRow],
    ) -> None:
        self.session.add_all(
            [
                TransactionRecord(
                    time_precision=row.time_precision,
                    account_id=account_id,
                    import_batch_id=import_batch_id,
                    source_row_number=row.row_number,
                    source_fingerprint=row.fingerprint,
                    booking_date=row.booking_date,
                    occurred_at=row.occurred_at,
                    merchant=row.merchant,
                    description=row.description,
                    amount=row.amount,
                    currency=row.currency,
                )
                for row in rows
            ]
        )
        await self.session.flush()
