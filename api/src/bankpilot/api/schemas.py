"""
文件职责：定义 BankPilot v1 认证、卡片、账单导入、运行、事件流与分类修正接口契约。

主要内容：
- 认证契约：`RegisterRequest`、`LoginRequest` 与 `UserResponse`。
- 卡片契约：`CardResponse` 与 `CardListResponse`。
- 导入契约：CSV 内容、字段映射、批次统计和失败行。
- 运行契约：`CreateRunRequest`、`RunResponse` 与 `AuditEventResponse`。
- 分类契约：`CorrectCategoryRequest` 只接受稳定分类代码。
- 系统契约：`HealthResponse`。

关键边界：外部请求禁止额外字段，并对邮箱、密码和用户消息设置结构限制。
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from bankpilot.domain.contracts import CardStatus, RunResult, TransactionCategory
from bankpilot.domain.statement_import import StatementFieldMapping

MAX_IMPORT_BYTES = 10 * 1024 * 1024


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RegisterRequest(BaseModel):
    """约束公开注册输入；确认密码只属于界面交互，不进入 API 契约。"""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr


class CardResponse(BaseModel):
    id: UUID
    account_id: UUID
    account_name: str
    display_name: str
    last_four: str
    status: CardStatus


class CardListResponse(BaseModel):
    items: list[CardResponse]


class ImportStatementRequest(BaseModel):
    """接收浏览器读取的 CSV 文本；原文件不会保存到服务器文件系统。"""

    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=MAX_IMPORT_BYTES)
    account_name: str = Field(min_length=1, max_length=100)
    currency: str = Field(min_length=3, max_length=3)
    mapping: StatementFieldMapping

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.isprintable():
            raise ValueError("file_name contains control characters")
        if normalized != normalized.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]:
            raise ValueError("file_name must not contain a path")
        if not normalized.lower().endswith((".csv", ".xlsx")):
            raise ValueError("only CSV and XLSX files are supported")
        return normalized

    @field_validator("content")
    @classmethod
    def validate_content_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_IMPORT_BYTES:
            raise ValueError("CSV exceeds the 10 MB limit")
        return value

    @field_validator("account_name")
    @classmethod
    def normalize_account_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("account_name is required")
        return normalized

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha() or not normalized.isascii():
            raise ValueError("currency must be a three-letter ISO code")
        return normalized


class ImportRowErrorResponse(BaseModel):
    row_number: int
    code: str
    message: str


class ImportBatchResponse(BaseModel):
    source: str
    skipped_rows: int
    excluded: list[ImportRowErrorResponse]
    id: UUID
    account_id: UUID | None
    account_name: str
    currency: str
    file_name: str
    status: Literal["COMPLETED", "COMPLETED_WITH_DUPLICATES", "REJECTED", "REVOKED"]
    total_rows: int
    imported_rows: int
    duplicate_rows: int
    error_rows: int
    start_date: date | None
    end_date: date | None
    field_mapping: dict[str, str | None]
    errors: list[ImportRowErrorResponse]
    created_at: datetime


class ImportBatchListResponse(BaseModel):
    items: list[ImportBatchResponse]


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=2, max_length=1_000)


class CorrectCategoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: TransactionCategory


class AuditEventResponse(BaseModel):
    sequence: int
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime


class RunResponse(BaseModel):
    id: UUID
    status: str
    user_message: str
    result: RunResult | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    events: list[AuditEventResponse]


class HealthResponse(BaseModel):
    status: str
