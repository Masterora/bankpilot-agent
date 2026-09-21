"""
文件职责：提供确定性账本查询、搜索、详情及导出接口。
主要内容：期间读取、多条件稳定分页、完整匹配 CSV 导出、带版本的详情读取和分类修正。
关键边界：按当前用户隔离；跨页、详情和导出校验版本，分类覆盖不修改源流水金额。
"""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.adapters.local_banking import LocalBankingGateway
from bankpilot.api.dependencies import (
    get_current_user,
    get_db_session,
    get_snapshot_session,
    get_snapshot_user,
)
from bankpilot.api.errors import ApiProblem
from bankpilot.api.schemas import CorrectCategoryRequest
from bankpilot.db.models import UserRecord
from bankpilot.db.transaction_repository import TransactionRepository
from bankpilot.domain.contracts import TransactionResult
from bankpilot.domain.transaction_search import (
    SearchDetail,
    SearchExport,
    SearchPage,
    SearchRequest,
)
from bankpilot.services import transaction_search

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


@router.get("", response_model=TransactionResult)
async def transactions(
    start_date: date,
    end_date: date,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> TransactionResult:
    if end_date < start_date or (end_date - start_date).days > 366:
        raise ApiProblem(422, "invalid_period", "End date must not precede start date")
    return await LocalBankingGateway(session).query_transactions(
        user_id=user.id, start_date=start_date, end_date=end_date
    )


@router.post("/search", response_model=SearchPage)
async def search_transactions(
    payload: SearchRequest,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> SearchPage:
    return await transaction_search.search(session, user.id, payload)


@router.post("/search/export")
async def export_transactions(
    payload: SearchExport,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> Response:
    await transaction_search.check_version(
        session, user.id, payload.expected_revision, payload.expected_search_version
    )
    items = await transaction_search.matching_items(session, user.id, payload.filters)
    return Response(
        transaction_search.export_csv(items),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="transactions.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{transaction_id}", response_model=SearchDetail)
async def transaction_detail(
    transaction_id: UUID,
    expected_revision: int | None = Query(default=None, ge=0),
    expected_search_version: str | None = Query(default=None, max_length=50),
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> SearchDetail:
    return await transaction_search.detail(
        session, user.id, transaction_id, expected_revision, expected_search_version
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
        expected_revision=payload.expected_revision,
    )
    if record is None:
        raise ApiProblem(404, "transaction_not_found", "Transaction not found")
    await session.commit()
