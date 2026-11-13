"""User-confirmed sandbox payments; all amounts and identities are server validated."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SandboxPaymentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    subject: str = Field(min_length=1, max_length=80)
    amount: Decimal = Field(gt=0, le=10000, max_digits=7, decimal_places=2)
    confirmation: Literal["确认沙箱支付"]

    @field_validator("subject")
    @classmethod
    def clean_subject(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("A printable payment subject is required")
        return value.strip()


class SandboxOrderView(BaseModel):
    id: UUID
    subject: str
    amount: Decimal
    status: str
    created_at: datetime
    expires_at: datetime
    checked_at: datetime | None
    checkout_url: str | None = None


class IntegrationStatus(BaseModel):
    feishu_enabled: bool
    feishu_bound: bool
    feishu_identity: str | None
    alipay_sandbox_enabled: bool


class BindingCodeView(BaseModel):
    code: str
    expires_at: datetime
