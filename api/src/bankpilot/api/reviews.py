"""
文件职责：提供规则核查、搜索结果核查投影与运行历史接口。
主要内容：查询规则证据、投影搜索匹配交易、保存用户判断、返回运行历史摘要。
关键边界：证据由服务端重算并校验版本；事务提交成功后才返回保存成功。
"""
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import (
    get_current_user,
    get_db_session,
    get_snapshot_session,
    get_snapshot_user,
)
from bankpilot.api.errors import ApiProblem
from bankpilot.db.models import UserRecord
from bankpilot.db.run_repository import RunRepository
from bankpilot.domain.contracts import ReviewList, ReviewState, RunStatus, TransactionQuery
from bankpilot.domain.transaction_search import ReviewProjection, ReviewProjectionRequest
from bankpilot.services.reviews import ReviewService, project_reviews

router = APIRouter(prefix="/api/v1", tags=["reviews"])


class ReviewRequest(TransactionQuery):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    key: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: ReviewState
    note: str = Field(default="", max_length=500)


class RunHistoryItem(BaseModel):
    id: UUID
    message: str
    status: RunStatus
    created_at: datetime


class RunHistory(BaseModel):
    items: list[RunHistoryItem]


@router.get("/reviews", response_model=ReviewList)
async def reviews(
    start_date: date,
    end_date: date,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReviewList:
    if end_date < start_date or (end_date - start_date).days > 366:
        raise ApiProblem(422, "invalid_period", "Select an ordered period of at most 366 days")
    return await ReviewService(session).read(user.id, start_date, end_date)


@router.post("/reviews", status_code=204)
async def save_review(
    payload: ReviewRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    saved = await ReviewService(session).save(
        user.id,
        payload.start_date,
        payload.end_date,
        payload.key,
        payload.state,
        payload.note,
        payload.expected_revision,
    )
    if not saved:
        raise ApiProblem(404, "evidence_unavailable", "Review evidence is no longer available")
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiProblem(
            409, "stale_version", "Review changed concurrently; reload and retry"
        ) from exc


@router.get("/run-history", response_model=RunHistory)
async def run_history(
    user: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> RunHistory:
    rows = await RunRepository(session).history_for_user(user.id)
    return RunHistory(
        items=[
            RunHistoryItem(
                id=row.id, message=row.user_message, status=row.status, created_at=row.created_at
            )
            for row in rows
        ]
    )


@router.post("/reviews/projection", response_model=ReviewProjection)
async def review_projection(
    payload: ReviewProjectionRequest,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> ReviewProjection:
    return await project_reviews(session, user.id, payload)
