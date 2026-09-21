"""
文件职责：提供用户认证、密码修改与 Cookie 会话接口。
主要内容：注册、登录、退出、读取当前用户、验证旧密码并撤销其他会话。
关键边界：只持久化密码和令牌的哈希；认证失败不泄露账户是否存在，密码修改在同一事务内完成。
"""
import asyncio

from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import (
    SESSION_COOKIE,
    get_app_settings,
    get_current_user,
    get_db_session,
)
from bankpilot.api.errors import ApiProblem
from bankpilot.api.schemas import ChangePasswordRequest, LoginRequest, RegisterRequest, UserResponse
from bankpilot.config import Settings
from bankpilot.db.models import UserRecord
from bankpilot.db.user_repository import SessionRepository, UserRepository
from bankpilot.security import (
    DUMMY_PASSWORD_HASH,
    create_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from bankpilot.services.passwords import change_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


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
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    try:
        async with session.begin():
            users = UserRepository(session)
            if await users.by_email(str(payload.email)) is not None:
                raise ApiProblem(
                    status.HTTP_409_CONFLICT, "email_registered", "Email already registered"
                )
            password_hash = await asyncio.to_thread(hash_password, payload.password)
            user = await users.add(email=str(payload.email), password_hash=password_hash)
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
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    async with session.begin():
        user = await UserRepository(session).by_email(str(payload.email), lock=True)
        candidate_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
        valid = await asyncio.to_thread(verify_password, payload.password, candidate_hash)
        if user is None or not valid:
            raise ApiProblem(
                status.HTTP_401_UNAUTHORIZED, "invalid_credentials", "Invalid credentials"
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


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
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


@router.get("/me", response_model=UserResponse)
async def me(user: UserRecord = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user.id, email=user.email)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def update_password(
    payload: ChangePasswordRequest,
    user: UserRecord = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> None:
    token_hash = hash_session_token(session_token or "", settings.session_secret.get_secret_value())
    try:
        await change_password(
            session,
            user_id=user.id,
            token_hash=token_hash,
            new_password=payload.new_password,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        code = str(exc)
        messages = {
            "session_expired": "Session expired",
            "password_unchanged": "New password must differ from current password",
        }
        if code not in messages:
            raise
        raise ApiProblem(401 if code == "session_expired" else 400, code, messages[code]) from exc
