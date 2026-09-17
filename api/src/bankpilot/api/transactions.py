"""
文件职责：提供确定性交易账本接口。

主要内容：包含日期范围查询和独立分类修正。

关键边界：查询不依赖模型，分类修正保存覆盖值但不修改源交易。
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.adapters.local_banking import LocalBankingGateway
from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.api.errors import ApiProblem
from bankpilot.api.schemas import CorrectCategoryRequest
from bankpilot.db.models import UserRecord
from bankpilot.db.transaction_repository import TransactionRepository
from bankpilot.domain.contracts import TransactionResult

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


@router.get("", response_model=TransactionResult)
async def transactions(
    start_date: date,
    end_date: date,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> TransactionResult:
    if end_date < start_date or (end_date - start_date).days > 366:
        raise ApiProblem(422, "invalid_period", "End date must not precede start date")
    return await LocalBankingGateway(session).query_transactions(
        user_id=user.id, start_date=start_date, end_date=end_date
    )


@router.post("/{transaction_id}/category", status_code=status.HTTP_204_NO_CONTENT)
async def correct_category(
    transaction_id: UUID,
    payload: CorrectCategoryRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    record = await TransactionRepository(session).set_category_override(
        user_id=user.id,
        transaction_id=transaction_id,
        category=payload.category.value,
    )
    if record is None:
        raise ApiProblem(404, "transaction_not_found", "Transaction not found")
    await session.commit()
