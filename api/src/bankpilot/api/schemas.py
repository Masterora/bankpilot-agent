"""
文件职责：定义 BankPilot v1 HTTP 接口的 Pydantic 请求与响应契约。

主要内容：
- 认证契约：`LoginRequest` 与 `UserResponse`。
- 运行契约：`CreateRunRequest`、`RunResponse` 与 `AuditEventResponse`。
- 系统契约：`HealthResponse`。

关键边界：外部请求禁止额外字段，并对邮箱、密码和用户消息设置结构限制。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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


class AuditEventResponse(BaseModel):
    sequence: int
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime


class RunResponse(BaseModel):
    id: UUID
    status: str
    user_message: str
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    events: list[AuditEventResponse]


class HealthResponse(BaseModel):
    status: str
