"""
文件职责：提供账本账户 HTTP 接口。

主要内容：包含账户列表、重命名请求校验与账本修订号更新。

关键边界：只能访问当前用户账户，重命名不改变账户身份和历史快照。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.db.account_repository import AccountRepository
from bankpilot.db.models import UserRecord

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


class AccountResponse(BaseModel):
    id: UUID
    name: str
    currency: str
    source: str


class AccountListResponse(BaseModel):
    items: list[AccountResponse]


class RenameAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Account name is required")
        return normalized


@router.get("", response_model=AccountListResponse)
async def accounts(
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AccountListResponse:
    rows = await AccountRepository(session).list_for_user(user.id)
    return AccountListResponse(
        items=[
            AccountResponse(id=row.id, name=row.name, currency=row.currency, source=row.source)
            for row in rows
        ]
    )


@router.post("/{account_id}/name", status_code=status.HTTP_204_NO_CONTENT)
async def rename_account(
    account_id: UUID,
    payload: RenameAccountRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    try:
        if not await AccountRepository(session).rename(user.id, account_id, payload.name):
            raise HTTPException(404, "Account not found")
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Account name already exists") from exc
