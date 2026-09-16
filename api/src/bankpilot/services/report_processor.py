"""
文件职责：执行持久化月报任务。

主要内容：领取任务、读取月度快照、构建报告并执行有限重试与失败收敛。

关键边界：执行时间短于租约，意外异常必须记录并收敛为终态。
"""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.db.report_repository import ReportRepository
from bankpilot.domain.reports import build_report, month_period
from bankpilot.errors import ReviewCapacityError, ToolExecutionError
from bankpilot.observability import job_timing
from bankpilot.ports import ReviewGateway

logger = logging.getLogger(__name__)


class ReportProcessor:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], gateway: ReviewGateway
    ) -> None:
        self.session_factory = session_factory
        self.gateway = gateway

    async def process_next(self) -> bool:
        async with self.session_factory() as session, session.begin():
            claim = await ReportRepository(session).claim()
        if claim is None:
            return False
        with job_timing(str(claim.id)):
            try:
                # 小于租约，失联 worker 不能在重新领取后提交结果。
                async with asyncio.timeout(45):
                    start, end = month_period(claim.month)
                    snapshot = await self.gateway.review_transactions(
                        user_id=claim.user_id,
                        start_date=start,
                        end_date=end,
                    )
                    report = build_report(claim.month, snapshot)
                    async with self.session_factory() as session, session.begin():
                        await ReportRepository(session).finish(claim, report)
            except ReviewCapacityError:
                async with self.session_factory() as session, session.begin():
                    await ReportRepository(session).fail(
                        claim, "report_period_limit", retryable=False
                    )
            except (ToolExecutionError, SQLAlchemyError, OSError, TimeoutError):
                async with self.session_factory() as session, session.begin():
                    await ReportRepository(session).fail(
                        claim, "report_generation_failed", retryable=True
                    )
            except Exception:
                logger.exception("Monthly report failed", extra={"report_id": str(claim.id)})
                async with self.session_factory() as session, session.begin():
                    await ReportRepository(session).fail(
                        claim, "report_internal_error", retryable=False
                    )
            return True

    async def run(self) -> None:
        while True:
            try:
                if await self.process_next():
                    continue
            except Exception:
                logger.exception("Monthly report queue unavailable")
            await asyncio.sleep(2)
