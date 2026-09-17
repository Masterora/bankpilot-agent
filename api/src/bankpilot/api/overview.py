"""
文件职责：提供财务总览的轻量只读接口。
主要内容：受限期间的调整汇总和最近五笔流水。
关键边界：不执行关系候选发现；关系核对仍由 relations 工作区负责。
"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import get_snapshot_session, get_snapshot_user
from bankpilot.api.errors import ApiProblem
from bankpilot.db.models import UserRecord
from bankpilot.db.overview_repository import read_overview
from bankpilot.domain.contracts import OverviewSnapshot
from bankpilot.errors import RelationError

router = APIRouter(prefix="/api/v1/overview", tags=["overview"])


@router.get("", response_model=OverviewSnapshot)
async def get_overview(
    start_date: date,
    end_date: date,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> OverviewSnapshot:
    """返回首屏所需数据，完整候选关系仅在关系核对页计算。"""
    if end_date < start_date or (end_date - start_date).days > 366:
        raise ApiProblem(422, "invalid_period")
    try:
        return await read_overview(session, user.id, start_date, end_date)
    except RelationError as exc:
        raise ApiProblem(exc.status, exc.code) from exc
