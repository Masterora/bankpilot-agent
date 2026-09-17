"""
文件职责：提供无持久化副作用的账单处理接口。

主要内容：包含文件解码、来源与字段识别、导入前预览。

关键边界：只捕获可预期的输入异常，预览与正式导入复用服务端解析规则。
"""

import base64
import binascii
import csv
import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from bankpilot.adapters.statement_files import decode_statement
from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.api.errors import ApiProblem
from bankpilot.api.schemas import ImportPreviewRequest, ImportRowErrorResponse
from bankpilot.db.models import UserRecord
from bankpilot.domain.source_detection import detect_statement
from bankpilot.domain.statement_import import (
    StatementFieldMapping,
    StatementStructureError,
)
from bankpilot.errors import StatementSizeError
from bankpilot.observability import measure
from bankpilot.services.accounts import resolve_account
from bankpilot.services.import_classification import classify_import
from bankpilot.services.statement_import import parse_input, request_digest

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


class PreviewRow(BaseModel):
    row_number: int
    date: date
    occurred_at: datetime
    time_precision: Literal["unknown", "date", "timestamp"]
    merchant: str
    amount: str
    classification: Literal["new", "duplicate"]


class PreviewAmounts(BaseModel):
    income: str
    expense: str
    net: str


class PreviewResponse(BaseModel):
    source: str
    parser_version: str
    request_digest: str
    currency: str
    skipped_rows: int
    excluded: list[ImportRowErrorResponse]
    total_rows: int
    valid_rows: int
    new_rows: int
    error_rows: int
    duplicate_rows: int
    issue_count: int
    issues_truncated: bool
    excluded_truncated: bool
    preview_truncated: bool
    valid_amounts: PreviewAmounts
    new_amounts: PreviewAmounts
    rows: list[PreviewRow]
    errors: list[ImportRowErrorResponse]


def amounts(values: list[Decimal]) -> PreviewAmounts:
    return PreviewAmounts(
        income=format(sum((v for v in values if v > 0), Decimal(0)), ".2f"),
        expense=format(-sum((v for v in values if v < 0), Decimal(0)), ".2f"),
        net=format(sum(values, Decimal(0)), ".2f"),
    )


@router.post("/preview", response_model=PreviewResponse)
async def preview(
    payload: ImportPreviewRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PreviewResponse:
    user_id = user.id
    await session.rollback()
    try:
        parsed, inferred_name = await run_in_threadpool(
            parse_input,
            payload.content,
            payload.mapping,
            payload.currency,
            payload.account_name,
            payload.account_id,
        )
    except StatementStructureError as exc:
        raise ApiProblem(422, "invalid_structure", str(exc)) from exc
    with measure("connection_ms"):
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    try:
        account = await resolve_account(
            session,
            user_id=user_id,
            account_id=payload.account_id,
            name=payload.account_name if payload.account_id else inferred_name,
            currency=payload.currency,
            source=parsed.source,
        )
        result = await classify_import(session, parsed, account.id if account else None)
    except ValueError as exc:
        raise ApiProblem(422, "account_unavailable", str(exc)) from exc
    finally:
        await session.rollback()
    valid = sorted(result.new + result.duplicates, key=lambda row: row.row_number)
    new_numbers = {row.row_number for row in result.new}
    return PreviewResponse(
        source=parsed.source,
        parser_version=parsed.parser_version,
        request_digest=request_digest(
            **payload.model_dump(exclude={"mapping"}), mapping=payload.mapping
        ),
        currency=payload.currency,
        skipped_rows=len(parsed.skipped),
        excluded=[ImportRowErrorResponse(**vars(e)) for e in parsed.skipped[:100]],
        total_rows=parsed.total_rows,
        valid_rows=len(valid),
        new_rows=len(result.new),
        error_rows=result.error_rows,
        duplicate_rows=len(result.duplicates),
        issue_count=len(result.errors),
        issues_truncated=len(result.errors) > 100,
        excluded_truncated=len(parsed.skipped) > 100,
        preview_truncated=len(valid) > 20,
        valid_amounts=amounts([row.amount for row in valid]),
        new_amounts=amounts([row.amount for row in result.new]),
        rows=[
            PreviewRow(
                row_number=row.row_number,
                date=row.booking_date,
                occurred_at=row.occurred_at,
                time_precision=row.time_precision,
                merchant=row.merchant,
                amount=str(row.amount),
                classification="new" if row.row_number in new_numbers else "duplicate",
            )
            for row in valid[:20]
        ],
        errors=[ImportRowErrorResponse(**vars(e)) for e in result.errors[:100]],
    )


class DetectRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10 * 1024 * 1024)


class DecodeRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    data: str = Field(min_length=1, max_length=14 * 1024 * 1024)


class DecodeResponse(BaseModel):
    content: str
    content_digest: str


@router.post("/decode", response_model=DecodeResponse)
async def decode_file(
    payload: DecodeRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DecodeResponse:
    await session.rollback()
    try:
        raw = base64.b64decode(payload.data, validate=True)
        content = await run_in_threadpool(decode_statement, payload.file_name, raw)
    except StatementSizeError as exc:
        raise ApiProblem(413, "file_too_large", str(exc)) from exc
    except (ValueError, binascii.Error) as exc:
        raise ApiProblem(422, "invalid_structure", str(exc)) from exc
    return DecodeResponse(
        content=content, content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest()
    )


class DetectionResponse(BaseModel):
    source: str
    parser_version: str
    headers: list[str]
    mapping: StatementFieldMapping
    account_name: str | None
    currency: str | None


@router.post("/detect", response_model=DetectionResponse)
async def detect(
    payload: DetectRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DetectionResponse:
    await session.rollback()
    return await run_in_threadpool(detect_content, payload.content)


def detect_content(content: str) -> DetectionResponse:
    if len(content.encode("utf-8")) > 10 * 1024 * 1024:
        raise ApiProblem(413, "file_too_large", "Statement exceeds the size limit")
    try:
        return DetectionResponse.model_validate(detect_statement(content), from_attributes=True)
    except (ValueError, csv.Error) as exc:
        raise ApiProblem(422, "invalid_structure", str(exc)) from exc
