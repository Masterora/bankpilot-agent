"""Load two owned successful reports in one consistent snapshot."""

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.report_repository import ReportRepository
from bankpilot.domain.report_comparison import ReportComparison, compare_reports
from bankpilot.domain.reports import MonthlySnapshot, ReportStatus
from bankpilot.errors import PlanningError


async def compare(
    session: AsyncSession, uid: UUID, before_id: UUID, after_id: UUID
) -> ReportComparison:
    if before_id == after_id:
        raise PlanningError("report_comparison_same", 422)
    repo = ReportRepository(session)
    before = await repo.get_for_user(uid, before_id)
    after = await repo.get_for_user(uid, after_id)
    if before is None or after is None:
        raise PlanningError("report_not_found", 404)
    if any(r.status != ReportStatus.SUCCEEDED or r.snapshot is None for r in (before, after)):
        raise PlanningError("report_not_ready", 409)
    first = MonthlySnapshot.model_validate(before.snapshot)
    second = MonthlySnapshot.model_validate(after.snapshot)
    if max(len(first.transactions.items), len(second.transactions.items)) > 10_000:
        raise PlanningError("report_comparison_capacity", 422)
    result = await asyncio.to_thread(compare_reports, before_id, after_id, first, second)
    result.before.update(
        created_at=before.created_at.isoformat(),
        completed_at=before.completed_at.isoformat() if before.completed_at else None,
    )
    result.after.update(
        created_at=after.created_at.isoformat(),
        completed_at=after.completed_at.isoformat() if after.completed_at else None,
    )
    return result
