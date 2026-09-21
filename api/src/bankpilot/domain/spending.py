"""消费查询范围与证据响应；金额为 Decimal，范围不能指定用户。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import BudgetEvidence, Currency, PlanningInput


class SpendingScope(PlanningInput):
    month: date
    category: TransactionCategory
    currency: Currency

    @field_validator("month")
    @classmethod
    def valid_month(cls, value: date) -> date:
        if value.day != 1 or not 1900 <= value.year <= 9998:
            raise ValueError("Expected first day of an eligible month")
        return value

    @field_validator("category")
    @classmethod
    def expense_category(cls, value: TransactionCategory) -> TransactionCategory:
        if value == TransactionCategory.INCOME:
            raise ValueError("Expected expense category")
        return value


class SpendingQuery(SpendingScope):
    expected_revision: int = Field(ge=0)
    expected_calculation_version: str = Field(min_length=1, max_length=64)
    page: int = Field(default=1, ge=1, le=1_000_000)


class SpendingCoverage(BaseModel):
    transaction_count: int
    latest_transaction_date: date | None


class SpendingSummary(BaseModel):
    scope: SpendingScope
    ledger_revision: int
    calculation_version: str
    calculated_at: datetime
    gross_spending: Decimal
    refund_offset: Decimal
    net_spending: Decimal
    contribution_count: int
    coverage: SpendingCoverage


class SpendingPage(BaseModel):
    summary: SpendingSummary
    page: int
    page_size: int
    total: int
    items: list[BudgetEvidence]
