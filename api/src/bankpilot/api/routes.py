"""
文件职责：定义 BankPilot v1 的认证、卡片、Agent、事件流与账单分类修正路由。

主要内容：
- 系统接口：`healthz` 和数据库 `readyz`。
- 认证接口：注册、登录、退出与当前用户查询。
- 卡片接口：读取当前用户所属账户下的卡片。
- 运行接口：创建异步 Agent 运行，按 ID 读取状态，并通过 SSE 增量订阅事件。
- 分析接口：在运行归属范围内修正交易分类并重新计算确定性分析。
- `_run_response`：组装运行记录和时间线响应。

关键边界：运行和交易必须同时匹配当前用户；SSE 序号用于断线续传与去重。
"""

import asyncio
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.api.dependencies import (
    SESSION_COOKIE,
    get_app_settings,
    get_current_user,
    get_db_session,
)
from bankpilot.api.schemas import (
    AuditEventResponse,
    CardListResponse,
    CardResponse,
    CorrectCategoryRequest,
    CreateRunRequest,
    HealthResponse,
    LoginRequest,
    RegisterRequest,
    RunResponse,
    UserResponse,
)
from bankpilot.config import Settings
from bankpilot.db.models import RunRecord, UserRecord
from bankpilot.db.repositories import (
    CardRepository,
    RunRepository,
    SessionRepository,
    TransactionRepository,
    UserRepository,
)
from bankpilot.domain.bill_analysis import analyze_bill
from bankpilot.domain.contracts import (
    CategorySource,
    RunResult,
    RunStatus,
    TransactionResult,
)
from bankpilot.security import (
    DUMMY_PASSWORD_HASH,
    create_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/v1")


def _set_session_cookie(
    response: Response, *, token: str, settings: Settings
) -> None:
    """统一设置注册和登录会话，确保 Cookie 安全属性不会漂移。"""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.get("/healthz", response_model=HealthResponse, tags=["system"])
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=HealthResponse, tags=["system"])
async def readyz(session: AsyncSession = Depends(get_db_session)) -> HealthResponse:
    await session.execute(text("SELECT 1"))
    return HealthResponse(status="ready")


@router.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
)
async def register(
    payload: RegisterRequest,
    response: Response,
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """创建唯一用户并直接建立会话，原始密码和会话令牌均不入库。"""
    try:
        async with session.begin():
            users = UserRepository(session)
            if await users.by_email(str(payload.email)) is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already registered",
                )

            # Argon2 密码哈希移到线程，避免阻塞异步 HTTP 处理。
            password_hash = await asyncio.to_thread(hash_password, payload.password)
            user = await users.add(email=str(payload.email), password_hash=password_hash)
            token = create_session_token()
            token_hash = hash_session_token(
                token, settings.session_secret.get_secret_value()
            )
            await SessionRepository(session).create(
                user_id=user.id,
                token_hash=token_hash,
                ttl_seconds=settings.session_ttl_seconds,
            )
    except IntegrityError as exc:
        # 并发注册可能同时通过预查，最终仍由数据库唯一索引裁决。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc

    _set_session_cookie(response, token=token, settings=settings)
    return UserResponse(id=user.id, email=user.email)


@router.post("/auth/login", response_model=UserResponse, tags=["auth"])
async def login(
    payload: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """创建 HttpOnly 会话，同时降低通过耗时区分无效用户的可能性。"""
    async with session.begin():
        user = await UserRepository(session).by_email(str(payload.email))
        candidate_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
        # 即使邮箱不存在也执行密码校验，避免出现可被探测的快速路径。
        password_is_valid = verify_password(payload.password, candidate_hash)
        if user is None or not password_is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        token = create_session_token()
        token_hash = hash_session_token(token, settings.session_secret.get_secret_value())
        await SessionRepository(session).create(
            user_id=user.id,
            token_hash=token_hash,
            ttl_seconds=settings.session_ttl_seconds,
        )
    _set_session_cookie(response, token=token, settings=settings)
    return UserResponse(id=user.id, email=user.email)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
async def logout(
    response: Response,
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> None:
    if session_token:
        token_hash = hash_session_token(session_token, settings.session_secret.get_secret_value())
        async with session.begin():
            await SessionRepository(session).delete(token_hash)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


@router.get("/auth/me", response_model=UserResponse, tags=["auth"])
async def me(user: UserRecord = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user.id, email=user.email)


@router.get("/cards", response_model=CardListResponse, tags=["cards"])
async def list_cards(
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CardListResponse:
    """返回当前用户的卡片摘要，不向前端暴露完整卡号。"""
    rows = await CardRepository(session).list_for_user(user.id)
    return CardListResponse(
        items=[
            CardResponse(
                id=card.id,
                account_id=card.account_id,
                account_name=account_name,
                display_name=card.display_name,
                last_four=card.last_four,
                status=card.status,
            )
            for card, account_name in rows
        ]
    )


@router.post(
    "/runs", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED, tags=["runs"]
)
async def create_run(
    payload: CreateRunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RunResponse:
    """先持久化运行记录，再派发后台处理并返回 202。"""
    repository = RunRepository(session)
    run = await repository.create(user_id=user.id, user_message=payload.message.strip())
    await session.commit()
    background_tasks.add_task(request.app.state.run_processor.process, run.id)
    return await _run_response(repository, run)


@router.get("/runs/{run_id}", response_model=RunResponse, tags=["runs"])
async def get_run(
    run_id: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RunResponse:
    """仅当运行记录属于当前认证用户时才返回。"""
    repository = RunRepository(session)
    run = await repository.get_for_user(run_id=run_id, user_id=user.id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return await _run_response(repository, run)


@router.get("/runs/{run_id}/events", tags=["runs"])
async def stream_run_events(
    run_id: UUID,
    request: Request,
    after: int = Query(default=0, ge=0),
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """按审计序号输出 SSE；浏览器重连时不会重复已确认事件。"""
    repository = RunRepository(session)
    run = await repository.get_for_user(run_id=run_id, user_id=user.id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    cursor = after
    last_event_id = request.headers.get("last-event-id")
    if last_event_id is not None:
        try:
            cursor = int(last_event_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Last-Event-ID"
            ) from exc
        if cursor < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Last-Event-ID"
            )

    session_factory = cast(
        async_sessionmaker[AsyncSession], request.app.state.session_factory
    )

    async def generate() -> AsyncIterator[str]:
        """每次轮询使用短会话，确保能够看到后台任务刚提交的事件。"""
        current_sequence = cursor
        idle_cycles = 0
        yield "retry: 1000\n\n"
        while not await request.is_disconnected():
            async with session_factory() as stream_session:
                stream_repository = RunRepository(stream_session)
                current_run = await stream_repository.get_for_user(
                    run_id=run_id, user_id=user.id
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


@router.post(
    "/runs/{run_id}/transactions/{transaction_id}/category",
    response_model=RunResponse,
    tags=["analysis"],
)
async def correct_transaction_category(
    run_id: UUID,
    transaction_id: UUID,
    payload: CorrectCategoryRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RunResponse:
    """保存用户分类修正，并重新生成该次运行的确定性统计。"""
    runs = RunRepository(session)
    run = await runs.get_for_user(run_id=run_id, user_id=user.id)
    if run is None or run.status != RunStatus.SUCCEEDED.value or run.result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    transactions = TransactionResult.model_validate(run.result.get("transactions"))
    item = next((entry for entry in transactions.items if entry.id == transaction_id), None)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    transaction = await TransactionRepository(session).set_category_override(
        user_id=user.id,
        transaction_id=transaction_id,
        category=payload.category.value,
    )
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    previous_category = item.category
    item.category = payload.category
    item.category_source = CategorySource.USER
    item.category_rule_id = "category_user_override_v1"
    result = RunResult(
        message=str(run.result.get("message", "")),
        transactions=transactions,
        analysis=analyze_bill(transactions.items),
    )
    await runs.update_result(run_id, result.model_dump(mode="json"))
    await runs.add_event(
        run_id,
        "transaction.category_corrected",
        {
            "transaction_id": str(transaction_id),
            "previous_category": previous_category.value,
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
        result=run.result,
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
