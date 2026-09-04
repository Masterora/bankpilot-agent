"""
文件职责：定义 BankPilot v1 认证、运行、事件流与分类修正接口契约。

主要内容：
- 认证契约：`LoginRequest` 与 `UserResponse`。
- 运行契约：`CreateRunRequest`、`RunResponse` 与 `AuditEventResponse`。
- 分类契约：`CorrectCategoryRequest` 只接受稳定分类代码。
- 系统契约：`HealthResponse`。

关键边界：外部请求禁止额外字段，并对邮箱、密码和用户消息设置结构限制。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from bankpilot.domain.contracts import RunResult, TransactionCategory


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr


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
