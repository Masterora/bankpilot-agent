"""
文件职责：提供当前用户的银行卡摘要接口。

主要内容：读取账户所属卡片并转换为隐藏完整卡号的响应。

关键边界：卡片必须通过账户归属在 SQL 查询中隔离用户。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.api.schemas import CardListResponse, CardResponse
from bankpilot.db.card_repository import CardRepository
from bankpilot.db.models import UserRecord
from bankpilot.domain.contracts import CardStatus

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])


@router.get("", response_model=CardListResponse)
async def list_cards(
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CardListResponse:
    rows = await CardRepository(session).list_for_user(user.id)
    return CardListResponse(
        items=[
            CardResponse(
                id=card.id,
                account_id=card.account_id,
                account_name=account_name,
                display_name=card.display_name,
                last_four=card.last_four,
                status=CardStatus(card.status),
            )
            for card, account_name in rows
        ]
    )
