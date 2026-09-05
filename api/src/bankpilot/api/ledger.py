"""
文件职责：提供无需模型参与的账户、交易账本与导入预览接口。

主要内容：账户列表、日期范围账本查询、独立分类修正和 CSV 预览报告。
关键边界：所有数据按登录用户隔离；预览不持久化，分类修正不覆盖源交易。
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.adapters.local_banking import LocalBankingGateway
from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.api.schemas import CorrectCategoryRequest, ImportStatementRequest
from bankpilot.db.models import (
    AccountRecord,
    ImportBatchRecord,
    TransactionCategoryOverrideRecord,
    TransactionRecord,
    UserRecord,
)
from bankpilot.db.repositories import TransactionRepository
from bankpilot.domain.contracts import TransactionResult
from bankpilot.domain.statement_import import parse_statement_csv

router = APIRouter(prefix="/api/v1", tags=["ledger"])


@router.post("/imports/{batch_id}/revoke", status_code=204)
async def revoke_import(
    batch_id: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """撤销该批次写入的交易，保留批次报告与历史运行快照供追溯。"""
    batch = await session.scalar(
        select(ImportBatchRecord)
        .where(ImportBatchRecord.id == batch_id, ImportBatchRecord.user_id == user.id)
        .with_for_update()
    )
    if batch is None:
        raise HTTPException(404, "Import not found")
    ids = select(TransactionRecord.id).where(TransactionRecord.import_batch_id == batch.id)
    await session.execute(
        delete(TransactionCategoryOverrideRecord).where(
            TransactionCategoryOverrideRecord.transaction_id.in_(ids)
        )
    )
    await session.execute(
        delete(TransactionRecord).where(TransactionRecord.import_batch_id == batch.id)
    )
    batch.status = "REVOKED"
    await session.commit()


class AccountResponse(BaseModel):
    id: UUID
    name: str
    currency: str


class AccountListResponse(BaseModel):
    items: list[AccountResponse]


@router.get("/accounts", response_model=AccountListResponse)
async def accounts(
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AccountListResponse:
    """返回实际存在的账本账户，不推断银行卡状态。"""
    rows = await session.scalars(
        select(AccountRecord)
        .where(AccountRecord.user_id == user.id)
        .order_by(AccountRecord.created_at, AccountRecord.id)
    )
    return AccountListResponse(
        items=[AccountResponse(id=row.id, name=row.name, currency=row.currency) for row in rows]
    )


@router.get("/transactions", response_model=TransactionResult)
async def transactions(
    start_date: date,
    end_date: date,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> TransactionResult:
    """账本浏览不依赖 Agent 运行或模型可用性。"""
    if end_date < start_date:
        raise HTTPException(422, "End date must not precede start date")
    return await LocalBankingGateway(session).query_transactions(
        user_id=user.id, start_date=start_date, end_date=end_date
    )


@router.post("/transactions/{transaction_id}/category", status_code=204)
async def correct_category(
    transaction_id: UUID,
    payload: CorrectCategoryRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """保存账本分类覆盖；既有运行快照保留生成时的结果。"""
    record = await TransactionRepository(session).set_category_override(
        user_id=user.id, transaction_id=transaction_id, category=payload.category.value
    )
    if record is None:
        raise HTTPException(404, "Transaction not found")
    await session.commit()


class PreviewRow(BaseModel):
    row_number: int
    date: date
    merchant: str
    amount: str


class PreviewResponse(BaseModel):
    total_rows: int
    error_rows: int
    rows: list[PreviewRow]


@router.post("/imports/preview", response_model=PreviewResponse)
async def preview(
    payload: ImportStatementRequest,
    user: UserRecord = Depends(get_current_user),
) -> PreviewResponse:
    """使用与提交完全一致的解析器预览，失败行阻止确认写入。"""
    parsed = parse_statement_csv(
        content=payload.content, mapping=payload.mapping, currency=payload.currency
    )
    return PreviewResponse(
        total_rows=parsed.total_rows,
        error_rows=len(parsed.errors),
        rows=[
            PreviewRow(
                row_number=row.row_number,
                date=row.booking_date,
                merchant=row.merchant,
                amount=str(row.amount),
            )
            for row in parsed.rows[:20]
        ],
    )
