"""HTTP interface for deterministic, persistent attention handling."""

from datetime import UTC, date, datetime
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import get_current_user, get_db_session, get_detached_user_id
from bankpilot.api.errors import ApiProblem
from bankpilot.db.models import UserRecord
from bankpilot.domain.attention import (
    AttentionGroup,
    AttentionPreference,
    AttentionPreferenceInput,
    AttentionReceipt,
    AttentionResponse,
    AttentionStateInput,
    AttentionType,
)
from bankpilot.errors import PlanningError
from bankpilot.services import attention as attention_service

router = APIRouter(prefix="/api/v1/attention", tags=["attention"])


def checked_month(value: date) -> date:
    if value.day != 1 or not 1900 <= value.year <= 9998:
        raise ApiProblem(422, "invalid_month", "Month out of range")
    return value


async def _read_group(
    request: Request,
    user_id: object,
    month: date,
    source_type: Literal["budget", "recurring"],
    now: datetime,
) -> AttentionGroup:
    try:
        async with request.app.state.session_factory() as session:
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            return await attention_service.read_group(
                session, cast(UUID, user_id), month, source_type, now
            )
    except PlanningError as exc:
        return AttentionGroup(
            status="unavailable",
            code="attention_unavailable" if exc.code == "planning_period_limit" else exc.code,
            retryable=exc.code == "planning_period_limit",
            read_at=now,
        )
    except (SQLAlchemyError, TimeoutError, OSError):
        return AttentionGroup(
            status="unavailable", code="data_unavailable", retryable=True, read_at=now
        )


@router.get("", response_model=AttentionResponse)
async def attention(
    request: Request,
    month: date,
    group: Literal["all", "budgets", "recurring"] = "all",
    user_id: UUID = Depends(get_detached_user_id),
) -> AttentionResponse:
    month = checked_month(month)
    now = datetime.now(UTC)
    budgets = (
        await _read_group(request, user_id, month, "budget", now)
        if group in ("all", "budgets")
        else None
    )
    recurring = (
        await _read_group(request, user_id, month, "recurring", now)
        if group in ("all", "recurring")
        else None
    )
    groups = [item for item in (budgets, recurring) if item is not None]
    if groups and all(item.status == "unavailable" for item in groups):
        raise ApiProblem(
            503, "attention_unavailable", "Attention items are temporarily unavailable"
        )
    return AttentionResponse(
        month=month,
        server_time=now,
        next_refresh_at=attention_service.next_refresh_at(groups, now),
        budgets=budgets,
        recurring=recurring,
    )


@router.get("/preferences", response_model=list[AttentionPreference])
async def preferences(
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[AttentionPreference]:
    return await attention_service.read_preferences(session, user.id)


@router.post("/state", response_model=AttentionReceipt)
async def change_state(
    payload: AttentionStateInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AttentionReceipt:
    try:
        receipt = await attention_service.change_state(session, user.id, payload, datetime.now(UTC))
        await session.commit()
        return receipt
    except PlanningError as exc:
        if exc.code == "planning_period_limit":
            raise ApiProblem(422, "attention_unavailable") from exc
        raise ApiProblem(exc.status, exc.code) from exc


@router.post("/preferences/{attention_type}", response_model=AttentionReceipt)
async def change_preference(
    attention_type: AttentionType,
    payload: AttentionPreferenceInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AttentionReceipt:
    try:
        receipt = await attention_service.change_preference(
            session, user.id, attention_type, payload
        )
        await session.commit()
        return receipt
    except PlanningError as exc:
        raise ApiProblem(exc.status, exc.code) from exc
