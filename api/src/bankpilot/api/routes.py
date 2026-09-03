"""
文件职责：定义 BankPilot v1 的 HTTP 路由与请求编排。

主要内容：
- 系统接口：`healthz` 和数据库 `readyz`。
- 认证接口：登录、退出与当前用户查询。
- 运行接口：创建异步 Agent 运行，按 ID 读取状态与审计事件。
- `_run_response`：组装运行记录和时间线响应。

关键边界：运行查询必须同时匹配 `run_id` 和当前 `user_id`；会话 Cookie 使用 HttpOnly。
"""

from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import (
    SESSION_COOKIE,
    get_app_settings,
    get_current_user,
    get_db_session,
)
from bankpilot.api.schemas import (
    AuditEventResponse,
    CreateRunRequest,
    HealthResponse,
    LoginRequest,
    RunResponse,
    UserResponse,
)
from bankpilot.config import Settings
from bankpilot.db.models import RunRecord, UserRecord
from bankpilot.db.repositories import RunRepository, SessionRepository, UserRepository
from bankpilot.security import (
    DUMMY_PASSWORD_HASH,
    create_session_token,
    hash_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/v1")


@router.get("/healthz", response_model=HealthResponse, tags=["system"])
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=HealthResponse, tags=["system"])
async def readyz(session: AsyncSession = Depends(get_db_session)) -> HealthResponse:
    await session.execute(text("SELECT 1"))
    return HealthResponse(status="ready")


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
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
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
