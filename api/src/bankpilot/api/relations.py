"""
文件职责：提供独立于模型的交易关系工作区与确认接口。
主要内容：受限期间查询、候选证据、调整汇总和带版本的确认、拒绝、撤销。
关键边界：请求不接收金额或用户 ID；业务服务验证身份、事实及互斥条件。
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.db.models import UserRecord
from bankpilot.domain.contracts import RelationWorkspace
from bankpilot.domain.transaction_relations import RelationKind, RelationState
from bankpilot.services.transaction_relations import (
    RelationError,
    relation_workspace,
    save_relation,
)

router = APIRouter(prefix="/api/v1/relations", tags=["relations"])


class RelationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: RelationKind
    first_id: UUID
    second_id: UUID
    state: RelationState
    expected_version: int = Field(ge=0)


@router.get("", response_model=RelationWorkspace)
async def list_relations(
    start_date: date,
    end_date: date,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RelationWorkspace:
    """同时返回期间原流水与调整值；候选未穷尽时明确标记。"""
    if end_date < start_date or (end_date - start_date).days > 366:
        raise HTTPException(422, "invalid_period")
    try:
        return RelationWorkspace.model_validate(
            await relation_workspace(session, user.id, start_date, end_date)
        )
    except RelationError as exc:
        raise HTTPException(exc.status, exc.code) from exc


@router.post("", status_code=204)
async def decide_relation(
    payload: RelationRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """事务完成才返回成功；冲突要求刷新，禁止覆盖另一页面的确认。"""
    try:
        await save_relation(session, user_id=user.id, **payload.model_dump())
    except RelationError as exc:
        raise HTTPException(exc.status, exc.code) from exc
