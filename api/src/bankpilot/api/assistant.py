"""助手 HTTP 边界：认证对话和显式确认分离，模型不接触确认端点。"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import (
    get_current_user,
    get_db_session,
    get_snapshot_session,
    get_snapshot_user,
)
from bankpilot.api.errors import ApiProblem
from bankpilot.db.assistant_repository import conversation_record, delete_history, lock_owner
from bankpilot.db.models import AssistantActionRecord, UserRecord
from bankpilot.domain.assistant import (
    ActionInput,
    ConversationDetail,
    ConversationPage,
    ScopeInput,
    TurnInput,
    TurnView,
)
from bankpilot.domain.spending import SpendingPage, SpendingQuery, SpendingScope
from bankpilot.errors import BankPilotError, RelationError
from bankpilot.services.assistant import resolve_action
from bankpilot.services.conversations import ConversationService, current_action
from bankpilot.services.spending import spending_page

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


@router.get("/spending-evidence", response_model=SpendingPage)
async def evidence(
    query: Annotated[SpendingQuery, Query()],
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> SpendingPage:
    scope = SpendingScope(month=query.month, category=query.category, currency=query.currency)
    return await spending_page(
        session,
        user.id,
        scope,
        query.expected_revision,
        query.expected_calculation_version,
        query.page,
    )


@router.post("/chat")
async def legacy_conversation() -> None:
    raise ApiProblem(
        409, "assistant_protocol_upgrade", "Refresh the page to use conversation history"
    )


def service(request: Request) -> ConversationService:
    return ConversationService(request.app.state.session_factory, request.app.state.settings)


@router.post("/turns", response_model=TurnView)
async def submit_turn(
    payload: TurnInput,
    request: Request,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> TurnView:
    uid = user.id
    await session.rollback()
    try:
        return await service(request).submit(uid, payload, request.app.state.assistant_gateway)
    except RelationError as exc:
        raise ApiProblem(exc.status, exc.code) from exc
    except BankPilotError as exc:
        raise ApiProblem(503, exc.code) from exc


@router.get("/turns/{request_id}", response_model=TurnView)
async def get_turn(
    request_id: UUID,
    request: Request,
    conversation_id: UUID | None = None,
    creation_id: UUID | None = None,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> TurnView:
    uid = user.id
    await session.rollback()
    return await service(request).lookup(uid, request_id, conversation_id, creation_id)


@router.get("/conversations", response_model=ConversationPage)
async def list_conversations(
    request: Request,
    cursor: UUID | None = None,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationPage:
    uid = user.id
    await session.rollback()
    return await service(request).listing(uid, cursor)


@router.get("/conversations/{identity}", response_model=ConversationDetail)
async def get_conversation(
    identity: UUID,
    request: Request,
    before: int | None = Query(None, ge=1),
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationDetail:
    uid = user.id
    await session.rollback()
    return await service(request).detail(uid, identity, before)


@router.post("/conversations/{identity}/scope")
async def set_scope(
    identity: UUID,
    payload: ScopeInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    await lock_owner(session, user.id)
    row = await conversation_record(session, user.id, identity, lock=True)
    row.month = payload.month
    row.scope = (
        payload.spending_context.model_dump(mode="json") if payload.spending_context else None
    )
    await session.commit()
    return {"saved": True}


@router.post("/conversations/{identity}/delete")
async def remove_conversation(
    identity: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    await lock_owner(session, user.id)
    row = await conversation_record(session, user.id, identity, lock=True)
    await delete_history(session, row)
    await session.commit()
    return {"deleted": True}


@router.post("/confirm")
async def confirm(
    payload: ActionInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    result = await resolve_action(session, user.id, payload.id, cancel=False)
    row = await session.get(AssistantActionRecord, payload.id)
    if row is not None:
        result = await current_action(session, row)
    await session.commit()
    return result


@router.post("/cancel")
async def cancel(
    payload: ActionInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    result = await resolve_action(session, user.id, payload.id, cancel=True)
    row = await session.get(AssistantActionRecord, payload.id)
    if row is not None:
        result = await current_action(session, row)
    await session.commit()
    return result
