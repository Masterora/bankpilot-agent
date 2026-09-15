"""
文件职责：提供无持久化副作用的账单处理接口。

主要内容：包含文件解码、来源与字段识别、导入前预览。

关键边界：只捕获可预期的输入异常，预览与正式导入复用服务端解析规则。
"""

import base64
import binascii
import csv
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from bankpilot.adapters.statement_files import decode_statement
from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.api.schemas import ImportStatementRequest
from bankpilot.db.models import UserRecord
from bankpilot.db.transaction_repository import TransactionRepository
from bankpilot.domain.payment_sources import locate_source, source_account
from bankpilot.domain.source_detection import detect_account, detect_mapping, read_csv_headers
from bankpilot.domain.statement_import import StatementFieldMapping, parse_statement_csv
from bankpilot.services.accounts import resolve_account

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


class PreviewRow(BaseModel):
    row_number: int
    date: date
    occurred_at: datetime
    time_precision: str
    merchant: str
    amount: str


class PreviewResponse(BaseModel):
    source: str
    skipped_rows: int
    excluded: list[dict[str, str | int]]
    total_rows: int
    error_rows: int
    duplicate_rows: int
    rows: list[PreviewRow]
    errors: list[dict[str, str | int]]


@router.post("/preview", response_model=PreviewResponse)
async def preview(
    payload: ImportStatementRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PreviewResponse:
    parsed = parse_statement_csv(
        content=payload.content,
        mapping=payload.mapping,
        currency=payload.currency,
    )
    try:
        account_name = (
            payload.account_name
            if payload.account_id
            else source_account(payload.content, payload.account_name)
        )
        account = await resolve_account(
            session,
            user_id=user.id,
            account_id=payload.account_id,
            name=account_name,
            currency=payload.currency,
            source=parsed.source,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    existing = (
        await TransactionRepository(session).existing_fingerprints(
            account_id=account.id,
            fingerprints={row.fingerprint for row in parsed.rows},
        )
        if account
        else set()
    )
    conflicts = (
        await TransactionRepository(session).conflicting_rows(
            account_id=account.id,
            rows=parsed.rows,
        )
        if account
        else []
    )
    errors: list[dict[str, str | int]] = [
        {"row_number": item.row_number, "message": item.message} for item in parsed.errors
    ]
    errors.extend(
        {"row_number": number, "message": "Transaction identifier conflicts with saved data"}
        for number in conflicts
    )
    return PreviewResponse(
        source=parsed.source,
        skipped_rows=len(parsed.skipped),
        excluded=[
            {"row_number": item.row_number, "message": item.message} for item in parsed.skipped
        ],
        total_rows=parsed.total_rows,
        error_rows=len(errors),
        errors=errors[:100],
        duplicate_rows=sum(row.fingerprint in existing for row in parsed.rows),
        rows=[
            PreviewRow(
                row_number=row.row_number,
                date=row.booking_date,
                occurred_at=row.occurred_at,
                time_precision=row.time_precision,
                merchant=row.merchant,
                amount=str(row.amount),
            )
            for row in parsed.rows[:20]
        ],
    )


class DetectRequest(BaseModel):
    content: str


class DecodeRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    data: str = Field(min_length=1, max_length=14 * 1024 * 1024)


@router.post("/decode")
async def decode_file(
    payload: DecodeRequest,
    user: UserRecord = Depends(get_current_user),
) -> dict[str, str]:
    try:
        raw = base64.b64decode(payload.data, validate=True)
        content = await run_in_threadpool(decode_statement, payload.file_name, raw)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"content": content}


class DetectionResponse(BaseModel):
    source: str
    headers: list[str]
    mapping: StatementFieldMapping
    account_name: str | None
    currency: str | None


@router.post("/detect", response_model=DetectionResponse)
async def detect(
    payload: DetectRequest,
    user: UserRecord = Depends(get_current_user),
) -> DetectionResponse:
    if len(payload.content.encode("utf-8")) > 10 * 1024 * 1024:
        raise HTTPException(413, "Statement exceeds the size limit")
    try:
        mapping = detect_mapping(payload.content)
        account_name, currency = detect_account(payload.content, mapping)
        return DetectionResponse(
            source=(
                native.profile.key if (native := locate_source(payload.content)) else "standard"
            ),
            headers=read_csv_headers(payload.content),
            mapping=mapping,
            account_name=account_name,
            currency=currency,
        )
    except (ValueError, csv.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
