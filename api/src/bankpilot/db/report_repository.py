"""
文件职责：封装月报持久任务与快照写入。

主要内容：按用户读取报告、幂等提交、额度限制、任务领取恢复、完成和删除。

关键边界：不隐式提交；列表不加载快照；领取令牌与租约约束写回，删除使旧 worker 失效。
"""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from bankpilot.db.models import MonthlyReportRecord, UserRecord
from bankpilot.domain.reports import MonthlySnapshot, ReportStatus

MAX_ATTEMPTS = 3
MAX_ACTIVE_PER_USER = 2
LEASE_SECONDS = 90


class ReportConflict(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class ReportClaim:
    id: UUID
    user_id: UUID
    month: date
    token: UUID
    attempt: int


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_user(
        self, user_id: UUID, report_id: UUID, *, include_snapshot: bool = True
    ) -> MonthlyReportRecord | None:
        statement = select(MonthlyReportRecord).where(
            MonthlyReportRecord.id == report_id,
            MonthlyReportRecord.user_id == user_id,
            MonthlyReportRecord.status != ReportStatus.DELETED,
        )
        if not include_snapshot:
            statement = statement.options(defer(MonthlyReportRecord.snapshot))
        record: MonthlyReportRecord | None = await self.session.scalar(statement)
        return record

    async def list_for_user(
        self, user_id: UUID, *, offset: int, limit: int
    ) -> list[MonthlyReportRecord]:
        return list(
            await self.session.scalars(
                select(MonthlyReportRecord)
                .options(defer(MonthlyReportRecord.snapshot))
                .where(
                    MonthlyReportRecord.user_id == user_id,
                    MonthlyReportRecord.status != ReportStatus.DELETED,
                )
                .order_by(MonthlyReportRecord.created_at.desc(), MonthlyReportRecord.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )

    async def delete_for_user(self, user_id: UUID, report_id: UUID) -> bool:
        """保留幂等墓碑，清除证据和领取令牌；调用方提交后删除才生效。"""
        record = await self.session.scalar(
            select(MonthlyReportRecord)
            .where(
                MonthlyReportRecord.id == report_id,
                MonthlyReportRecord.user_id == user_id,
            )
            .with_for_update()
        )
        if record is None:
            return False
        record.status = ReportStatus.DELETED
        record.snapshot = None
        record.ledger_revision = None
        record.rule_version = None
        record.claim_token = None
        record.lease_until = None
        record.error_code = None
        return True

    async def submit(self, user_id: UUID, month: date, key: UUID) -> MonthlyReportRecord:
        # 请求与账本写入遵循同一用户锁顺序；额度检查和新增任务不可分离。
        user = await self.session.scalar(
            select(UserRecord.id).where(UserRecord.id == user_id).with_for_update()
        )
        if user is None:
            raise ReportConflict("report_not_found", 404)
        existing = await self.session.scalar(
            select(MonthlyReportRecord).where(
                MonthlyReportRecord.user_id == user_id,
                MonthlyReportRecord.idempotency_key == key,
            )
        )
        if existing is not None:
            if existing.status == ReportStatus.DELETED:
                raise ReportConflict("report_deleted", 410)
            if existing.month != month:
                raise ReportConflict("idempotency_conflict")
            return existing
        active = await self.session.scalar(
            select(func.count())
            .select_from(MonthlyReportRecord)
            .where(
                MonthlyReportRecord.user_id == user_id,
                MonthlyReportRecord.status.in_([ReportStatus.QUEUED, ReportStatus.RUNNING]),
            )
        )
        if active is not None and active >= MAX_ACTIVE_PER_USER:
            raise ReportConflict("report_quota_exceeded", 429)
        record = MonthlyReportRecord(user_id=user_id, month=month, idempotency_key=key)
        self.session.add(record)
        await self.session.flush()
        return record

    async def claim(self) -> ReportClaim | None:
        # 最后一次尝试期间进程退出，也必须最终收敛为失败。
        await self.session.execute(
            update(MonthlyReportRecord)
            .where(
                MonthlyReportRecord.status == ReportStatus.RUNNING,
                MonthlyReportRecord.lease_until <= func.now(),
                MonthlyReportRecord.attempts >= MAX_ATTEMPTS,
            )
            .values(
                status=ReportStatus.FAILED,
                error_code="report_attempts_exhausted",
                claim_token=None,
                lease_until=None,
                completed_at=func.now(),
            )
        )
        record = await self.session.scalar(
            select(MonthlyReportRecord)
            .where(
                MonthlyReportRecord.attempts < MAX_ATTEMPTS,
                or_(
                    and_(
                        MonthlyReportRecord.status == ReportStatus.QUEUED,
                        MonthlyReportRecord.available_at <= func.now(),
                    ),
                    and_(
                        MonthlyReportRecord.status == ReportStatus.RUNNING,
                        MonthlyReportRecord.lease_until <= func.now(),
                    ),
                ),
            )
            .order_by(MonthlyReportRecord.available_at, MonthlyReportRecord.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        record.status = ReportStatus.RUNNING
        record.attempts += 1
        record.claim_token = uuid4()
        record.error_code = None
        await self.session.execute(
            update(MonthlyReportRecord)
            .where(
                MonthlyReportRecord.id == record.id,
            )
            .values(lease_until=func.now() + timedelta(seconds=LEASE_SECONDS))
        )
        return ReportClaim(
            record.id, record.user_id, record.month, record.claim_token, record.attempts
        )

    async def finish(self, claim: ReportClaim, snapshot: MonthlySnapshot) -> None:
        await self.session.execute(
            update(MonthlyReportRecord)
            .where(
                MonthlyReportRecord.id == claim.id,
                MonthlyReportRecord.status == ReportStatus.RUNNING,
                MonthlyReportRecord.claim_token == claim.token,
                MonthlyReportRecord.lease_until > func.now(),
            )
            .values(
                status=ReportStatus.SUCCEEDED,
                snapshot=snapshot.model_dump(mode="json"),
                ledger_revision=snapshot.ledger_revision,
                rule_version=snapshot.report_rule_version,
                completed_at=func.now(),
                lease_until=None,
                claim_token=None,
                error_code=None,
            )
        )

    async def fail(self, claim: ReportClaim, code: str, *, retryable: bool) -> None:
        retry = retryable and claim.attempt < MAX_ATTEMPTS
        await self.session.execute(
            update(MonthlyReportRecord)
            .where(
                MonthlyReportRecord.id == claim.id,
                MonthlyReportRecord.status == ReportStatus.RUNNING,
                MonthlyReportRecord.claim_token == claim.token,
                MonthlyReportRecord.lease_until > func.now(),
            )
            .values(
                status=ReportStatus.QUEUED if retry else ReportStatus.FAILED,
                error_code=code,
                available_at=func.now() + timedelta(seconds=2**claim.attempt),
                completed_at=None if retry else func.now(),
                claim_token=None,
                lease_until=None,
            )
        )
