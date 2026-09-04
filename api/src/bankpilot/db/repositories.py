"""
文件职责：封装数据库查询、数据归属过滤与 Agent 运行状态持久化。

主要内容：
- `UserRepository`：用户查询与创建。
- `SessionRepository`：创建、解析和删除可过期会话。
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
    RunRecord,
    SessionRecord,
    TransactionCategoryOverrideRecord,
    TransactionRecord,
    UserRecord,
)
from bankpilot.domain.contracts import RunStatus


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
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
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
                TransactionRecord.occurred_at >= start,
                TransactionRecord.occurred_at < end,
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
