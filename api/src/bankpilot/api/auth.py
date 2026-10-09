"""
文件职责：提供用户认证、密码修改与 Cookie 会话接口。
主要内容：注册、登录、退出、读取当前用户、验证旧密码并撤销其他会话。
关键边界：只持久化密码和令牌的哈希；认证失败不泄露账户是否存在，密码修改在同一事务内完成。
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import (
    SESSION_COOKIE,
    check_ui_identity,
    get_app_settings,
    get_current_user,
    get_db_session,
    get_snapshot_session,
    get_snapshot_user,
)
from bankpilot.api.errors import ApiProblem
from bankpilot.api.schemas import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from bankpilot.config import Settings
from bankpilot.db.models import UserRecord
from bankpilot.db.user_repository import SessionRepository, UserRepository
from bankpilot.security import (
    DUMMY_PASSWORD_HASH,
    create_session_token,
    hash_password_async,
    hash_session_token,
    verify_password_async,
)
from bankpilot.services.account_data import delete_account, export_account
from bankpilot.services.passwords import change_password
from bankpilot.services.registration import register_user
from bankpilot.services.security_admission import SecurityAdmission

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@asynccontextmanager
async def password_slot(request: Request, account: str) -> AsyncIterator[None]:
    settings = request.app.state.settings
    admission = SecurityAdmission(request.app.state.session_factory, settings)
    # Ignore forwarded headers: the documented proxy is not an authenticated IP authority.
    await admission.auth(request.client.host if request.client else "unknown", account)
    async with admission.lease("password", account.casefold(), 1, settings.password_concurrency):
        yield


def _set_session_cookie(response: Response, *, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    response: Response,
    request: Request,
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    try:
        async with password_slot(request, str(payload.email)):
            password_hash = await hash_password_async(payload.password)
            async with session.begin():
                users = UserRepository(session)
                if await users.by_email(str(payload.email)) is not None:
                    raise ApiProblem(
                        status.HTTP_409_CONFLICT, "email_registered", "Email already registered"
                    )
                user = await register_user(
                    session,
                    email=str(payload.email),
                    password_hash=password_hash,
                    settings=settings,
                )
                token = create_session_token()
                token_hash = hash_session_token(token, settings.session_secret.get_secret_value())
                await SessionRepository(session).create(
                    user_id=user.id,
                    token_hash=token_hash,
                    ttl_seconds=settings.session_ttl_seconds,
                )
    except IntegrityError as exc:
        raise ApiProblem(
            status.HTTP_409_CONFLICT, "email_registered", "Email already registered"
        ) from exc
    _set_session_cookie(response, token=token, settings=settings)
    return UserResponse(id=user.id, email=user.email)


@router.post("/login", response_model=UserResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    async with password_slot(request, str(payload.email)):
        async with session.begin():
            candidate = await UserRepository(session).by_email(str(payload.email))
            candidate_hash = candidate.password_hash if candidate else DUMMY_PASSWORD_HASH
        valid = await verify_password_async(payload.password, candidate_hash)
        async with session.begin():
            user = await UserRepository(session).by_email(str(payload.email), lock=True)
            if user is None or not valid or user.password_hash != candidate_hash:
                raise ApiProblem(401, "invalid_credentials", "Invalid credentials")
            token = create_session_token()
            token_hash = hash_session_token(token, settings.session_secret.get_secret_value())
            await SessionRepository(session).create(
                user_id=user.id,
                token_hash=token_hash,
                ttl_seconds=settings.session_ttl_seconds,
            )
    _set_session_cookie(response, token=token, settings=settings)
    return UserResponse(id=user.id, email=user.email)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    request: Request,
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> None:
    if session_token:
        token_hash = hash_session_token(session_token, settings.session_secret.get_secret_value())
        async with session.begin():
            owner = await SessionRepository(session).resolve_user(token_hash)
            if owner is not None:
                check_ui_identity(request, owner.id)
            await SessionRepository(session).delete(token_hash)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


@router.get("/me", response_model=UserResponse)
async def me(user: UserRecord = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user.id, email=user.email)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def update_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: UserRecord = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> None:
    token_hash = hash_session_token(session_token or "", settings.session_secret.get_secret_value())
    uid = user.id
    await session.rollback()
    try:
        async with password_slot(request, f"user:{uid}"):
            await change_password(
                session,
                user_id=uid,
                token_hash=token_hash,
                current_password=payload.current_password,
                new_password=payload.new_password,
            )
            replacement = create_session_token()
            sessions = SessionRepository(session)
            await sessions.delete(token_hash)
            await sessions.create(
                user_id=uid,
                token_hash=hash_session_token(
                    replacement, settings.session_secret.get_secret_value()
                ),
                ttl_seconds=settings.session_ttl_seconds,
            )
            await session.commit()
        _set_session_cookie(response, token=replacement, settings=settings)
    except ValueError as exc:
        await session.rollback()
        code = str(exc)
        messages = {
            "session_expired": "Session expired",
            "password_unchanged": "New password must differ from current password",
            "current_password_invalid": "Current password is incorrect",
        }
        if code not in messages:
            raise
        raise ApiProblem(401 if code == "session_expired" else 400, code, messages[code]) from exc


@router.post("/data-export")
async def account_export(
    response: Response,
    request: Request,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    admission = SecurityAdmission(request.app.state.session_factory, request.app.state.settings)
    async with asyncio.timeout(30), admission.lease("data_export", str(user.id), 1, 2):
        return await export_account(session, user.id)


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def account_delete(
    payload: DeleteAccountRequest,
    request: Request,
    response: Response,
    user: UserRecord = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> None:
    uid = user.id
    token_hash = hash_session_token(session_token or "", settings.session_secret.get_secret_value())
    await session.rollback()
    async with password_slot(request, f"user:{uid}"):
        await delete_account(session, uid, token_hash, payload.current_password)
        await session.commit()
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax"
    )
