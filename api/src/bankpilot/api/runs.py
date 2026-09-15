"""
文件职责：提供 Agent 运行 HTTP 接口。

主要内容：包含创建与读取运行、SSE 事件流和运行内分类修正。

关键边界：运行与交易必须同时属于当前用户，事件序号支持断线续传和去重。
"""

import asyncio
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.api.schemas import (
    AuditEventResponse,
    CorrectCategoryRequest,
    CreateRunRequest,
    RunResponse,
)
from bankpilot.db.models import (
    AccountRecord,
    RunRecord,
    TransactionCategoryOverrideRecord,
    TransactionRecord,
    UserRecord,
)
from bankpilot.db.run_repository import RunRepository
from bankpilot.db.transaction_repository import TransactionRepository
from bankpilot.domain.bill_analysis import classify_transaction
from bankpilot.domain.contracts import RunResult, RunStatus, TransactionResult

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@router.post("", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: CreateRunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RunResponse:
    repository = RunRepository(session)
    run = await repository.create(user_id=user.id, user_message=payload.message.strip())
    await session.commit()
    background_tasks.add_task(request.app.state.run_processor.process, run.id)
    return await _run_response(repository, run)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RunResponse:
    repository = RunRepository(session)
    run = await repository.get_for_user(run_id=run_id, user_id=user.id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return await _run_response(repository, run)


@router.get("/{run_id}/events")
async def stream_run_events(
    run_id: UUID,
    request: Request,
    after: int = Query(default=0, ge=0),
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    repository = RunRepository(session)
    run = await repository.get_for_user(run_id=run_id, user_id=user.id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    cursor = after
    last_event_id = request.headers.get("last-event-id")
    if last_event_id is not None:
        try:
            cursor = int(last_event_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Last-Event-ID") from exc
        if cursor < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Last-Event-ID")
    session_factory = cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)

    async def generate() -> AsyncIterator[str]:
        current_sequence = cursor
        idle_cycles = 0
        yield "retry: 1000\n\n"
        while not await request.is_disconnected():
            async with session_factory() as stream_session:
                stream_repository = RunRepository(stream_session)
                current_run = await stream_repository.get_for_user(
                    run_id=run_id,
                    user_id=user.id,
                )
                if current_run is None:
                    return
                events = await stream_repository.events_after(run_id, current_sequence)
            for event in events:
                payload = AuditEventResponse(
                    sequence=event.sequence,
                    event_type=event.event_type,
                    payload=event.payload,
                    occurred_at=event.occurred_at,
                )
                yield f"id: {event.sequence}\ndata: {payload.model_dump_json()}\n\n"
                current_sequence = event.sequence
            if current_run.status in {
                RunStatus.SUCCEEDED.value,
                RunStatus.FAILED.value,
                RunStatus.UNKNOWN.value,
            }:
                return
            idle_cycles += 1
            if idle_cycles % 60 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{run_id}/transactions/{transaction_id}/category", response_model=RunResponse)
async def correct_transaction_category(
    run_id: UUID,
    transaction_id: UUID,
    payload: CorrectCategoryRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RunResponse:
    await session.scalar(select(UserRecord).where(UserRecord.id == user.id).with_for_update())
    runs = RunRepository(session)
    run = await runs.get_for_user(run_id=run_id, user_id=user.id)
    if run is None or run.status != RunStatus.SUCCEEDED.value or run.result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    transactions = TransactionResult.model_validate(run.result.get("transactions"))
    if not any(entry.id == transaction_id for entry in transactions.items):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    current = await session.scalar(
        select(TransactionRecord)
        .join(AccountRecord)
        .where(TransactionRecord.id == transaction_id, AccountRecord.user_id == user.id)
        .with_for_update()
    )
    if current is None:
        raise HTTPException(404, "Transaction not found")
    override = await session.get(TransactionCategoryOverrideRecord, transaction_id)
    previous_category = (
        override.category
        if override
        else classify_transaction(
            merchant=current.merchant,
            description=current.description,
            amount=current.amount,
        ).category.value
    )
    transaction = await TransactionRepository(session).set_category_override(
        user_id=user.id,
        transaction_id=transaction_id,
        category=payload.category.value,
    )
    if transaction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    await runs.add_event(
        run_id,
        "transaction.category_corrected",
        {
            "transaction_id": str(transaction_id),
            "previous_category": previous_category,
            "category": payload.category.value,
        },
    )
    await session.commit()
    await session.refresh(run)
    return await _run_response(runs, run)


async def _run_response(repository: RunRepository, run: RunRecord) -> RunResponse:
    events = await repository.events(run.id)
    return RunResponse(
        id=run.id,
        status=run.status,
        user_message=run.user_message,
        result=RunResult.model_validate(run.result) if run.result is not None else None,
        error_code=run.error_code,
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
        events=[
            AuditEventResponse(
                sequence=event.sequence,
                event_type=event.event_type,
                payload=event.payload,
                occurred_at=event.occurred_at,
            )
            for event in events
        ],
    )
