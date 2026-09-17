"""文件职责：周期日期、预算证据与规划接口契约；金额使用 Decimal，不执行自动扣款。"""

import calendar
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bankpilot.domain.contracts import TransactionCategory

Money = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class PlanningInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BudgetInput(PlanningInput):
    budget_id: UUID | None = None
    month: date
    category: TransactionCategory
    currency: Currency
    amount: Money
    expected_version: int = Field(ge=0)

    @field_validator("category")
    @classmethod
    def expense_category(cls, value: TransactionCategory) -> TransactionCategory:
        if value == TransactionCategory.INCOME:
            raise ValueError("Income is not an expense budget")
        return value


class BudgetPurchase(BaseModel):
    id: UUID
    booking_date: date
    merchant: str
    account_name: str
    amount: Decimal


class BudgetEvidence(BaseModel):
    transaction_id: UUID
    booking_date: date
    merchant: str
    account_name: str
    category: TransactionCategory
    currency: str
    amount: Decimal
    contribution: Decimal
    purchase: BudgetPurchase | None = None


class BudgetItem(BaseModel):
    id: UUID
    category: TransactionCategory
    currency: str
    amount: Decimal
    spent: Decimal
    remaining: Decimal
    overspent: bool
    version: int
    transaction_count: int


class UnbudgetedCategory(BaseModel):
    category: TransactionCategory
    currency: str
    spent: Decimal
    transaction_count: int


class BudgetCopyResult(BaseModel):
    copied: int
    source_count: int


class BudgetCoverage(BaseModel):
    currency: str
    transaction_count: int
    latest_transaction_date: date | None
    limit: Decimal
    budgeted_spent: Decimal
    unbudgeted_spent: Decimal


class BudgetWorkspace(BaseModel):
    month: date
    items: list[BudgetItem]
    evidence: list[BudgetEvidence]
    unbudgeted: list[UnbudgetedCategory]
    spending: list[UnbudgetedCategory]
    coverage: list[BudgetCoverage]


class RecurringInput(PlanningInput):
    id: UUID
    name: str = Field(min_length=1, max_length=100)
    merchant: str = Field(min_length=1, max_length=160)
    account_id: UUID
    currency: Currency
    amount: Money
    cadence: Literal["monthly", "yearly"]
    start_date: date

    @field_validator("start_date")
    @classmethod
    def valid_date(cls, value: date) -> date:
        if not 1900 <= value.year <= 9998:
            raise ValueError("Date out of range")
        return value


class RecurringEditInput(RecurringInput):
    effective_month: date
    source_month: date
    expected_version: int = Field(ge=1)
    replace_revision: bool = False

    @field_validator("effective_month", "source_month")
    @classmethod
    def valid_month(cls, value: date) -> date:
        if value.day != 1 or not 1900 <= value.year <= 9998:
            raise ValueError("Expected first day of an eligible month")
        return value


class RecurringStatusInput(PlanningInput):
    status: Literal["active", "paused", "ended"]
    expected_version: int = Field(ge=1)


class RecurringMatchInput(PlanningInput):
    due_date: date
    transaction_id: UUID | None
    expected_version: int = Field(ge=1)


class RecurringSkipInput(PlanningInput):
    due_date: date
    skipped: bool
    expected_version: int = Field(ge=1)


class RecurringCancelRevisionInput(PlanningInput):
    effective_month: date
    expected_version: int = Field(ge=1)


class RecurringRevision(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    effective_month: date
    account_id: UUID
    merchant: str
    currency: str
    amount: Decimal
    cadence: Literal["monthly", "yearly"]
    start_date: date


class RecurringTransaction(BaseModel):
    id: UUID
    account_id: UUID
    booking_date: date
    merchant: str
    amount: Decimal
    currency: str
    eligible: bool


class RecurringOccurrence(BaseModel):
    due_date: date
    transaction: RecurringTransaction | None
    skipped: bool = False


class RecurringItem(RecurringInput):
    model_config = ConfigDict(from_attributes=True)
    status: Literal["active", "paused", "ended"]
    version: int
    latest_effective_month: date
    next_due_date: date | None
    future_revisions: list[RecurringRevision] = Field(default_factory=list)
    occurrences: list[RecurringOccurrence] = Field(default_factory=list)


class RecurringWorkspace(BaseModel):
    month: date
    items: list[RecurringItem]
    candidates: list[RecurringTransaction]


def due_in_month(start: date, cadence: str, month: date) -> date | None:
    """每次从起始日推算，月末截短不改变锚点，闰年年付不会永久漂移到 28 日。"""
    if (month.year, month.month) < (start.year, start.month):
        return None
    if cadence == "yearly" and month.month != start.month:
        return None
    day = min(start.day, calendar.monthrange(month.year, month.month)[1])
    return date(month.year, month.month, day)
