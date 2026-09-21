"""
文件职责：提供可恢复账单导入的 HTTP 生命周期接口。
主要内容：导入历史、按幂等键恢复结果、原子导入、批次撤销和响应转换。
关键边界：当前用户范围内操作；撤销清理源交易及关联并递增修订号，保留批次与历史快照。
"""
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.api.errors import ApiProblem
from bankpilot.api.schemas import (
    ImportBatchListResponse,
    ImportBatchResponse,
    ImportRowErrorResponse,
    ImportStatementRequest,
)
from bankpilot.db.import_repository import ImportRepository
from bankpilot.db.models import (
    ImportBatchRecord,
    TransactionRecord,
    UserRecord,
)
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.statement_import import StatementStructureError
from bankpilot.errors import ImportConflictError
from bankpilot.services.statement_import import StatementImportService

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


@router.get("", response_model=ImportBatchListResponse)
async def list_imports(
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ImportBatchListResponse:
    batches = await ImportRepository(session).list_for_user(user.id)
    return ImportBatchListResponse(items=[_import_response(batch) for batch in batches])


@router.post("", response_model=ImportBatchResponse, status_code=status.HTTP_201_CREATED)
async def import_statement(
    payload: ImportStatementRequest,
    response: Response,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ImportBatchResponse:
    user_id = user.id
    await session.rollback()
    try:
        batch, replay = await StatementImportService(session).execute(
            user_id=user_id,
            idempotency_key=payload.idempotency_key,
            file_name=payload.file_name,
            content=payload.content,
            account_name=payload.account_name,
            account_id=payload.account_id,
            currency=payload.currency,
            mapping=payload.mapping,
        )
    except ImportConflictError as exc:
        raise ApiProblem(
            status.HTTP_409_CONFLICT, "import_idempotency_conflict", "同一操作不能使用不同输入"
        ) from exc
    except StatementStructureError as exc:
        raise ApiProblem(422, "invalid_structure", str(exc)) from exc
    except ValueError as exc:
        raise ApiProblem(422, "account_unavailable", str(exc)) from exc
    response.status_code = 200 if replay else 201
    return _import_response(batch)


@router.get("/by-key/{key}", response_model=ImportBatchResponse)
async def import_by_key(
    key: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ImportBatchResponse:
    batch = await ImportRepository(session).by_key(user.id, key)
    if batch is None:
        raise ApiProblem(404, "import_not_found", "尚未查询到已提交结果")
    return _import_response(batch)


@router.post("/{batch_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_import(
    batch_id: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await session.scalar(select(UserRecord).where(UserRecord.id == user.id).with_for_update())
    batch = await session.scalar(
        select(ImportBatchRecord)
        .where(ImportBatchRecord.id == batch_id, ImportBatchRecord.user_id == user.id)
        .with_for_update()
    )
    if batch is None:
        raise ApiProblem(404, "import_not_found", "Import not found")
    deleted_id = await session.scalar(
        delete(TransactionRecord)
        .where(TransactionRecord.import_batch_id == batch.id)
        .returning(TransactionRecord.id)
    )
    # 外键级联清理分类与关系；只有账本事实改变才使历史报告过期。
    batch.status = "REVOKED"
    if deleted_id is not None:
        await UserRepository(session).bump_revision(user.id)
    await session.commit()


def _import_response(batch: ImportBatchRecord) -> ImportBatchResponse:
    source = batch.field_mapping.get("source")
    if not isinstance(source, str) or not source:
        raise RuntimeError(f"Import batch {batch.id} has no source")
    return ImportBatchResponse(
        source=source,
        parser_version=batch.parser_version,
        new_rows=batch.new_rows,
        valid_rows=batch.new_rows + batch.duplicate_rows if batch.new_rows is not None else None,
        skipped_rows=batch.skipped_rows,
        issue_count=batch.issue_count,
        issues_truncated=(
            batch.issue_count > sum(e.get("code") != "EXCLUDED" for e in batch.errors)
            if batch.issue_count is not None
            else None
        ),
        excluded_truncated=(
            batch.skipped_rows > sum(e.get("code") == "EXCLUDED" for e in batch.errors)
            if batch.skipped_rows is not None
            else None
        ),
        excluded=[
            ImportRowErrorResponse.model_validate(item)
            for item in batch.errors
            if item.get("code") == "EXCLUDED"
        ][:100],
        id=batch.id,
        account_id=batch.account_id,
        account_name=batch.account_name,
        currency=batch.currency,
        file_name=batch.file_name,
        status=cast(
            Literal["COMPLETED", "COMPLETED_WITH_DUPLICATES", "REJECTED", "REVOKED"],
            batch.status,
        ),
        total_rows=batch.total_rows,
        imported_rows=batch.imported_rows,
        duplicate_rows=batch.duplicate_rows,
        error_rows=batch.error_rows,
        start_date=batch.start_date,
        end_date=batch.end_date,
        field_mapping=batch.field_mapping,
        errors=[
            ImportRowErrorResponse.model_validate(item)
            for item in batch.errors
            if item.get("code") != "EXCLUDED"
        ][:100],
        created_at=batch.created_at,
    )
