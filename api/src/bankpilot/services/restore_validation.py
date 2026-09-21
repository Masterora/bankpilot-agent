"""
文件职责：核对备份一致性并准备离线任务恢复。
主要内容：生成结构与数据证据、校验数据库身份、收敛恢复库中的运行和助手任务状态。
关键边界：不启动 API、模型或消费者；连接显式提供，核对只读，准备仅修改指定恢复库。
"""
import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.base import SCHEMA_REVISION, Base
from bankpilot.db.models import (
    AccountRecord,
    AssistantActionRecord,
    AssistantConversationRecord,
    AssistantTurnRecord,
    MonthlyReportRecord,
    RunRecord,
    SessionRecord,
    TransactionRecord,
)
from bankpilot.db.report_repository import MAX_ATTEMPTS
from bankpilot.db.run_repository import RunRepository
from bankpilot.domain.contracts import RunStatus
from bankpilot.domain.reports import MonthlySnapshot
from bankpilot.services.schema_evidence import schema_digest


class DatabaseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    migration: str
    schema_hash: str
    counts: dict[str, int]
    hashes: dict[str, str]
    currency_totals: dict[str, str]


async def database_evidence(session: AsyncSession) -> DatabaseEvidence:
    """流式计算各表有序行摘要，不把敏感记录写入核对文件或日志。"""
    migration = str(await session.scalar(text("SELECT version_num FROM alembic_version")))
    if migration != SCHEMA_REVISION:
        raise ValueError(f"Use the application matching migration {SCHEMA_REVISION}")
    schema_hash = await schema_digest(session)
    counts, hashes = {}, {}
    for table in Base.metadata.sorted_tables:
        digest, count = hashlib.sha256(), 0
        result = await session.stream(select(table).order_by(*table.primary_key.columns))
        async for row in result.mappings():
            digest.update(
                json.dumps(
                    dict(row),
                    sort_keys=True,
                    default=str,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
            digest.update(b"\n")
            count += 1
        counts[table.name], hashes[table.name] = count, digest.hexdigest()
    totals = await session.execute(
        select(
            AccountRecord.user_id,
            TransactionRecord.currency,
            func.sum(TransactionRecord.amount),
        )
        .join(AccountRecord, AccountRecord.id == TransactionRecord.account_id)
        .group_by(
            AccountRecord.user_id,
            TransactionRecord.currency,
        )
        .order_by(AccountRecord.user_id, TransactionRecord.currency)
    )
    currency_totals = {
        f"{uid}:{currency}": format(amount, ".2f") for uid, currency, amount in totals
    }
    snapshots = await session.stream_scalars(
        select(MonthlyReportRecord.snapshot).where(
            MonthlyReportRecord.status == "SUCCEEDED",
        )
    )
    async for snapshot in snapshots:
        MonthlySnapshot.model_validate(snapshot)
    return DatabaseEvidence(
        migration=migration,
        schema_hash=schema_hash,
        counts=counts,
        hashes=hashes,
        currency_totals=currency_totals,
    )


async def database_identity(session: AsyncSession) -> dict[str, str]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT current_database() AS database, inet_server_addr()::text AS host, "
                    "inet_server_port()::text AS port"
                )
            )
        )
        .mappings()
        .one()
    )
    return {key: str(value) for key, value in row.items()}


async def prepare_restored_tasks(session: AsyncSession) -> dict[str, int]:
    """调用方必须隔离执行者并持有恢复事务；保留历史事实和尝试次数。"""
    reports = list(
        await session.scalars(
            select(MonthlyReportRecord)
            .where(
                MonthlyReportRecord.status == "RUNNING",
            )
            .with_for_update()
        )
    )
    runs = list(
        await session.scalars(
            select(RunRecord)
            .where(
                RunRecord.status.in_([RunStatus.CREATED, RunStatus.PLANNING, RunStatus.EXECUTING]),
            )
            .with_for_update()
        )
    )
    result = {"reports": len(reports), "runs": len(runs)}
    for report in reports:
        report.claim_token = None
        report.lease_until = None
        report.available_at = datetime.now(UTC)
        report.status = "QUEUED" if report.attempts < MAX_ATTEMPTS else "FAILED"
        report.error_code = "restore_interrupted"
        if report.status == "FAILED":
            report.completed_at = datetime.now(UTC)
    repository = RunRepository(session)
    for run in runs:
        run.status = RunStatus.UNKNOWN
        run.error_code = "OPERATION_STATUS_UNKNOWN"
        run.error_message = "Execution was interrupted by database restore"
        await repository.add_event(
            run.id,
            "run.failed",
            {
                "code": "OPERATION_STATUS_UNKNOWN",
                "status": RunStatus.UNKNOWN,
            },
        )
    # 备份之后已退出的会话不能在恢复库重新有效。
    await session.execute(
        update(AssistantActionRecord)
        .where(AssistantActionRecord.status == "pending")
        .values(status="cancelled")
    )
    await session.execute(delete(AssistantTurnRecord))
    await session.execute(
        update(AssistantConversationRecord).values(
            deleted=True,
            title=None,
            month=None,
            scope=None,
            search_context=None,
            context_version=0,
        )
    )
    await session.execute(delete(SessionRecord))
    return result
