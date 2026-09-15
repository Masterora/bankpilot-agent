"""
文件职责：封装 Agent 运行和审计事件持久化。

主要内容：实现状态迁移、计划与结果保存、过期恢复及增量事件读取。

关键边界：仓储不隐式提交，运行归属读取必须同时限定用户 ID。
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import AuditEventRecord, RunRecord
from bankpilot.domain.contracts import RunStatus


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, user_id: UUID, user_message: str) -> RunRecord:
        run = RunRecord(user_id=user_id, user_message=user_message, status=RunStatus.CREATED.value)
        self.session.add(run)
        await self.session.flush()
        await self.add_event(run.id, "run.created", {"status": run.status})
        return run

    async def history_for_user(self, user_id: UUID, limit: int = 50) -> list[RunRecord]:
        return list(
            await self.session.scalars(
                select(RunRecord)
                .where(RunRecord.user_id == user_id)
                .order_by(RunRecord.created_at.desc(), RunRecord.id.desc())
                .limit(limit)
            )
        )

    async def get_for_user(self, *, run_id: UUID, user_id: UUID) -> RunRecord | None:
        return cast(
            RunRecord | None,
            await self.session.scalar(
                select(RunRecord).where(RunRecord.id == run_id, RunRecord.user_id == user_id)
            ),
        )

    async def get(self, run_id: UUID) -> RunRecord | None:
        return await self.session.get(RunRecord, run_id, with_for_update=True)

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

    async def fail(self, run_id: UUID, *, code: str, message: str) -> None:
        await self.session.execute(
            update(RunRecord)
            .where(RunRecord.id == run_id)
            .values(status=RunStatus.FAILED.value, error_code=code, error_message=message[:500])
        )
        await self.add_event(run_id, "run.failed", {"code": code})

    async def reconcile_interrupted(self) -> int:
        interrupted = await self.session.scalars(
            select(RunRecord)
            .where(
                RunRecord.updated_at < datetime.now(UTC) - timedelta(seconds=120),
                RunRecord.status.in_(
                    [
                        RunStatus.CREATED.value,
                        RunStatus.PLANNING.value,
                        RunStatus.EXECUTING.value,
                    ]
                ),
            )
            .with_for_update(skip_locked=True)
        )
        records = list(interrupted)
        for run in records:
            run.status = RunStatus.UNKNOWN.value
            run.error_code = "OPERATION_STATUS_UNKNOWN"
            run.error_message = "The execution heartbeat expired before completion"
            await self.add_event(
                run.id,
                "run.failed",
                {"code": "OPERATION_STATUS_UNKNOWN", "status": RunStatus.UNKNOWN.value},
            )
        return len(records)

    async def add_event(self, run_id: UUID, event_type: str, payload: dict[str, Any]) -> None:
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
        result = await self.session.scalars(
            select(AuditEventRecord)
            .where(AuditEventRecord.run_id == run_id, AuditEventRecord.sequence > sequence)
            .order_by(AuditEventRecord.sequence)
        )
        return list(result)
