"""
文件职责：封装数据库查询、数据归属过滤与 Agent 运行状态持久化。

主要内容：
- `UserRepository`：用户查询与创建。
- `SessionRepository`：创建、解析和删除可过期会话。
- `AccountRepository`：按用户复用或创建导入账户。
- `ImportRepository`：保存并读取账单导入报告。
- `RunRepository`：运行创建、状态迁移、计划/结果记录、中断修复与增量事件读取。
- `CardRepository`：按当前用户所属账户读取卡片。
- `TransactionRepository`：查询交易并保存不覆盖原始数据的用户分类修正。

关键边界：带用户归属的读取必须在 SQL 条件中同时限定资源 ID 与用户 ID。
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import (
    AccountRecord,
    AuditEventRecord,
    CardRecord,
    ImportBatchRecord,
    RunRecord,
    SessionRecord,
    TransactionCategoryOverrideRecord,
    TransactionRecord,
    UserRecord,
)
from bankpilot.domain.contracts import RunStatus
from bankpilot.domain.statement_import import ParsedStatementRow


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_email(self, email: str) -> UserRecord | None:
        return cast(
            UserRecord | None,
            await self.session.scalar(select(UserRecord).where(UserRecord.email == email.lower())),
        )

    async def by_id(self, user_id: UUID) -> UserRecord | None:
        return await self.session.get(UserRecord, user_id)

    async def add(self, *, email: str, password_hash: str) -> UserRecord:
        user = UserRecord(email=email.lower(), password_hash=password_hash)
        self.session.add(user)
        await self.session.flush()
        return user


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, user_id: UUID, token_hash: str, ttl_seconds: int) -> SessionRecord:
        record = SessionRecord(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def resolve_user(self, token_hash: str) -> UserRecord | None:
        statement = (
            select(UserRecord)
            .join(SessionRecord, SessionRecord.user_id == UserRecord.id)
            .where(
                SessionRecord.token_hash == token_hash,
                SessionRecord.expires_at > datetime.now(UTC),
            )
        )
        return cast(UserRecord | None, await self.session.scalar(statement))

    async def delete(self, token_hash: str) -> None:
        await self.session.execute(
            delete(SessionRecord).where(SessionRecord.token_hash == token_hash)
        )


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(self, *, user_id: UUID, name: str, currency: str) -> AccountRecord:
        """账户名称和币种在用户范围内稳定复用，避免每次导入产生新账户。"""
        existing = cast(
            AccountRecord | None,
            await self.session.scalar(
                select(AccountRecord).where(
                    AccountRecord.user_id == user_id,
                    AccountRecord.name == name,
                    AccountRecord.currency == currency,
                )
            ),
        )
        if existing is not None:
            return existing
        account = AccountRecord(user_id=user_id, name=name, currency=currency)
        self.session.add(account)
        await self.session.flush()
        return account


class ImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        user_id: UUID,
        account_id: UUID | None,
        account_name: str,
        currency: str,
        file_name: str,
        file_hash: str,
        status: str,
        total_rows: int,
        imported_rows: int,
        duplicate_rows: int,
        error_rows: int,
        start_date: date | None,
        end_date: date | None,
        field_mapping: dict[str, str | None],
        errors: list[dict[str, Any]],
    ) -> ImportBatchRecord:
        batch = ImportBatchRecord(
            user_id=user_id,
            account_id=account_id,
            account_name=account_name,
            currency=currency,
            file_name=file_name,
            file_hash=file_hash,
            status=status,
            total_rows=total_rows,
            imported_rows=imported_rows,
            duplicate_rows=duplicate_rows,
            error_rows=error_rows,
            start_date=start_date,
            end_date=end_date,
            field_mapping=field_mapping,
            errors=errors,
        )
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def list_for_user(self, user_id: UUID) -> list[ImportBatchRecord]:
        records = await self.session.scalars(
            select(ImportBatchRecord)
            .where(ImportBatchRecord.user_id == user_id)
            .order_by(ImportBatchRecord.created_at.desc(), ImportBatchRecord.id.desc())
        )
        return list(records)


class CardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: UUID) -> list[tuple[CardRecord, str]]:
        """通过账户归属筛选卡片，避免依赖应用层二次过滤。"""
        rows = await self.session.execute(
            select(CardRecord, AccountRecord.name)
            .join(AccountRecord, CardRecord.account_id == AccountRecord.id)
            .where(AccountRecord.user_id == user_id)
            .order_by(CardRecord.created_at, CardRecord.id)
        )
        return list(rows.tuples())


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, user_id: UUID, user_message: str) -> RunRecord:
        run = RunRecord(user_id=user_id, user_message=user_message, status=RunStatus.CREATED.value)
        self.session.add(run)
        await self.session.flush()
        await self.add_event(run.id, "run.created", {"status": run.status})
        return run

    async def get_for_user(self, *, run_id: UUID, user_id: UUID) -> RunRecord | None:
        """同时按运行记录和所有者查询，防止调用方跨越租户边界。"""
        return cast(
            RunRecord | None,
            await self.session.scalar(
                select(RunRecord).where(RunRecord.id == run_id, RunRecord.user_id == user_id)
            ),
        )

    async def get(self, run_id: UUID) -> RunRecord | None:
        return await self.session.get(RunRecord, run_id)

    async def set_status(self, run_id: UUID, status: RunStatus) -> None:
        await self.session.execute(
            update(RunRecord).where(RunRecord.id == run_id).values(status=status.value)
        )

    async def set_plan(
        self, run_id: UUID, *, draft_action: dict[str, Any], model_info: dict[str, Any]
    ) -> None:
        await self.session.execute(
            update(RunRecord)
            .where(RunRecord.id == run_id)
            .values(draft_action=draft_action, model_info=model_info)
        )

    async def succeed(self, run_id: UUID, result: dict[str, Any]) -> None:
        await self.session.execute(
            update(RunRecord)
            .where(RunRecord.id == run_id)
            .values(
                status=RunStatus.SUCCEEDED.value, result=result, error_code=None, error_message=None
            )
        )
        await self.add_event(run_id, "run.completed", {"status": RunStatus.SUCCEEDED.value})

    async def update_result(self, run_id: UUID, result: dict[str, Any]) -> None:
        """更新已完成运行的派生分析结果，不改变运行终态。"""
        await self.session.execute(
            update(RunRecord).where(RunRecord.id == run_id).values(result=result)
        )

    async def fail(self, run_id: UUID, *, code: str, message: str) -> None:
        await self.session.execute(
            update(RunRecord)
            .where(RunRecord.id == run_id)
            .values(status=RunStatus.FAILED.value, error_code=code, error_message=message[:500])
        )
        await self.add_event(run_id, "run.failed", {"code": code})

    async def reconcile_interrupted(self) -> int:
        """重启后将非终态运行标记为未知，不虚构成功或失败结果。"""
        interrupted = await self.session.scalars(
            select(RunRecord).where(
                RunRecord.status.in_(
                    [
                        RunStatus.CREATED.value,
                        RunStatus.PLANNING.value,
                        RunStatus.EXECUTING.value,
                    ]
                )
            )
        )
        records = list(interrupted)
        for run in records:
            run.status = RunStatus.UNKNOWN.value
            run.error_code = "OPERATION_STATUS_UNKNOWN"
            run.error_message = "The service stopped before this run reached a terminal state"
            await self.add_event(
                run.id,
                "run.failed",
                {"code": "OPERATION_STATUS_UNKNOWN", "status": RunStatus.UNKNOWN.value},
            )
        return len(records)

    async def add_event(self, run_id: UUID, event_type: str, payload: dict[str, Any]) -> None:
        """向指定运行记录追加具有单调序号的审计事件。"""
        next_sequence = await self.session.scalar(
            select(func.coalesce(func.max(AuditEventRecord.sequence), 0) + 1).where(
                AuditEventRecord.run_id == run_id
            )
        )
        self.session.add(
            AuditEventRecord(
                run_id=run_id,
                sequence=int(next_sequence or 1),
                event_type=event_type,
                payload=payload,
            )
        )

    async def events(self, run_id: UUID) -> list[AuditEventRecord]:
        result = await self.session.scalars(
            select(AuditEventRecord)
            .where(AuditEventRecord.run_id == run_id)
            .order_by(AuditEventRecord.sequence)
        )
        return list(result)

    async def events_after(self, run_id: UUID, sequence: int) -> list[AuditEventRecord]:
        """按单调序号读取尚未发送的事件，供 SSE 断线续传。"""
        result = await self.session.scalars(
            select(AuditEventRecord)
            .where(AuditEventRecord.run_id == run_id, AuditEventRecord.sequence > sequence)
            .order_by(AuditEventRecord.sequence)
        )
        return list(result)


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def query_for_user(
        self, *, user_id: UUID, start_date: date, end_date: date
    ) -> list[tuple[TransactionRecord, str, str | None]]:
        """通过用户所属账户查询交易，时间范围使用 UTC 左闭右开区间。"""
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

    async def set_category_override(
        self, *, user_id: UUID, transaction_id: UUID, category: str
    ) -> TransactionRecord | None:
        """仅允许交易所属用户写入分类修正，并保留银行原始记录。"""
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
        return transaction

    async def existing_fingerprints(self, *, account_id: UUID, fingerprints: set[str]) -> set[str]:
        """一次读取账户内已有指纹，避免按行往返数据库。"""
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
        """相同来源标识若对应不同金额或交易内容，拒绝静默跳过。"""
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
        """在调用方事务中批量加入已校验交易，不在仓储层隐式提交。"""
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
