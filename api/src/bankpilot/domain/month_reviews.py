"""Explicit user declarations for an account month and their ledger evidence."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from bankpilot.domain.planning import PlanningInput


class MonthReviewInput(PlanningInput):
    month: date
    action: Literal["review", "close", "reopen"]
    expected_version: int = Field(ge=0)
    expected_revision: int = Field(ge=0)


class MonthReviewTotal(BaseModel):
    currency: str
    inflow: Decimal
    outflow: Decimal


class AccountMonthReview(BaseModel):
    account_id: UUID
    account_name: str
    month: date
    status: Literal["open", "reviewed", "closed", "stale"]
    saved_status: Literal["open", "reviewed", "closed"]
    version: int
    ledger_revision: int
    confirmed_at: datetime | None
    transaction_count: int
    first_transaction_date: date | None
    last_transaction_date: date | None
    totals: list[MonthReviewTotal]
    can_close: bool
