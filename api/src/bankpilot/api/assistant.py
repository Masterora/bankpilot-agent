"""助手 HTTP 边界：认证对话和显式确认分离，模型不接触确认端点。"""

import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.api.errors import ApiProblem
from bankpilot.db.models import UserRecord
from bankpilot.domain.assistant import ActionInput, ChatInput
from bankpilot.errors import BankPilotError, RelationError
from bankpilot.services.assistant import chat, resolve_action

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


@router.post("/chat")
async def conversation(
    payload: ChatInput,
    request: Request,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    uid = user.id
    await session.rollback()
    settings = request.app.state.settings
    try:
        async with asyncio.timeout(90):
            return await chat(
                request.app.state.session_factory,
                request.app.state.assistant_gateway,
                uid,
                payload,
                datetime.now(ZoneInfo(settings.business_timezone)).date(),
            )
    except TimeoutError as exc:
        raise ApiProblem(504, "assistant_timeout") from exc
    except RelationError as exc:
        raise ApiProblem(exc.status, exc.code, exc.code) from exc
    except BankPilotError as exc:
        raise ApiProblem(503, exc.code, exc.code) from exc


@router.post("/confirm")
async def confirm(
    payload: ActionInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    result = await resolve_action(session, user.id, payload.id, cancel=False)
    await session.commit()
    return result


@router.post("/cancel")
async def cancel(
    payload: ActionInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    result = await resolve_action(session, user.id, payload.id, cancel=True)
    await session.commit()
    return result
