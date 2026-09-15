"""
文件职责：提供规则核查与运行历史 HTTP 契约。
主要内容：校验查询范围、调用核查用例、转换历史摘要与业务错误。
关键边界：服务端重算证据；响应结构显式声明，事务提交成功后才返回保存成功。
"""

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.db.models import UserRecord
from bankpilot.db.run_repository import RunRepository
from bankpilot.domain.contracts import ReviewList, ReviewState, RunStatus, TransactionQuery
from bankpilot.services.reviews import ReviewService

router = APIRouter(prefix="/api/v1", tags=["reviews"])


class ReviewRequest(TransactionQuery):
    model_config = ConfigDict(extra="forbid")
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
        raise HTTPException(422, "Select an ordered period of at most 366 days")
    return await ReviewService(session).read(user.id, start_date, end_date)


@router.post("/reviews", status_code=204)
async def save_review(
    payload: ReviewRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    saved = await ReviewService(session).save(
        user.id, payload.start_date, payload.end_date, payload.key, payload.state, payload.note
    )
    if not saved:
        raise HTTPException(404, "Review evidence is no longer available")
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Review changed concurrently; reload and retry") from exc


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
