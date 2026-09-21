"""
文件职责：提供助手对话、上下文与预算提案的 HTTP 接口。
主要内容：提交和恢复轮次、分页读取与删除会话、更新消费范围及搜索上下文、确认或取消提案。
关键边界：所有操作绑定当前用户；模型不能调用确认端点，上下文更新与提案写入由服务端校验。
"""
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import (
    get_current_user,
    get_db_session,
    get_snapshot_session,
    get_snapshot_user,
)
from bankpilot.api.errors import ApiProblem
from bankpilot.db.assistant_repository import conversation_record, delete_history, lock_owner
from bankpilot.db.models import (
    AssistantActionRecord,
    AssistantConversationRecord,
    AssistantTurnRecord,
    UserRecord,
)
from bankpilot.domain.assistant import (
    ActionInput,
    ConversationDetail,
    ConversationPage,
    ConversationView,
    ScopeInput,
    SearchContextInput,
    TurnInput,
    TurnView,
)
from bankpilot.domain.spending import (
    ComparisonEvidencePage,
    ComparisonEvidenceQuery,
    SpendingComparison,
    SpendingPage,
    SpendingQuery,
    SpendingScope,
)
from bankpilot.errors import BankPilotError, PlanningError, RelationError
from bankpilot.services.assistant import resolve_action
from bankpilot.services.conversations import ConversationService, conversation_view, current_action
from bankpilot.services.spending import comparison_evidence_page, spending_page
from bankpilot.services.transaction_search import validate_ownership


def require_protocol(
    version: Annotated[str | None, Header(alias="X-Assistant-Protocol")] = None,
) -> None:
    if version != "4":
        raise ApiProblem(409, "assistant_protocol_upgrade", "Refresh the page to upgrade")


router = APIRouter(
    prefix="/api/v1/assistant",
    tags=["assistant"],
    dependencies=[Depends(require_protocol)],
)


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


@router.get(
    "/turns/{turn_id}/comparison-evidence", response_model=ComparisonEvidencePage
)
async def comparison_evidence(
    turn_id: UUID,
    query: Annotated[ComparisonEvidenceQuery, Query()],
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> ComparisonEvidencePage:
    turn = await session.scalar(
        select(AssistantTurnRecord)
        .join(
            AssistantConversationRecord,
            AssistantConversationRecord.id == AssistantTurnRecord.conversation_id,
        )
        .where(
            AssistantTurnRecord.id == turn_id,
            AssistantTurnRecord.status == "completed",
            AssistantTurnRecord.result_version == 3,
            AssistantConversationRecord.user_id == user.id,
            AssistantConversationRecord.deleted.is_(False),
        )
    )
    if turn is None:
        raise PlanningError("assistant_comparison_not_found", 404)
    items = [
        item
        for item in (turn.result or {}).get("evidence", [])
        if isinstance(item, dict) and item.get("tool") == "compare_spending"
    ]
    if len(items) != 1:
        raise PlanningError("assistant_comparison_not_found", 404)
    try:
        comparison = SpendingComparison.model_validate(items[0].get("data"))
    except ValueError as exc:
        raise PlanningError("assistant_comparison_not_found", 404) from exc
    return await comparison_evidence_page(
        session, user.id, comparison, query.side, query.category, query.page
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
) -> ConversationView:
    await lock_owner(session, user.id)
    row = await conversation_record(session, user.id, identity, lock=True)
    if row.context_version != payload.expected_context_version:
        raise PlanningError("assistant_context_stale", 409)
    row.context_version += 1
    row.month = payload.month
    row.scope = (
        payload.spending_context.model_dump(mode="json") if payload.spending_context else None
    )
    result = conversation_view(row)
    await session.commit()
    return result


@router.put("/conversations/{identity}/search-context", response_model=ConversationView)
async def set_search_context(
    identity: UUID,
    payload: SearchContextInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationView:
    await lock_owner(session, user.id)
    row = await conversation_record(session, user.id, identity, lock=True)
    if row.context_version != payload.expected_context_version:
        raise PlanningError("assistant_context_stale", 409)
    if payload.filters:
        await validate_ownership(session, user.id, payload.filters)
    row.search_context = payload.filters.model_dump(mode="json") if payload.filters else None
    row.context_version += 1
    result = conversation_view(row)
    await session.commit()
    return result


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
