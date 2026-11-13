"""Reusable limits; applying a template requires a frozen target preview."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import Currency, Money, PlanningInput


class TemplateEntry(PlanningInput):
    category: TransactionCategory
    currency: Currency
    amount: Money

    @field_validator("category")
    @classmethod
    def expense(cls, value: TransactionCategory) -> TransactionCategory:
        if value == TransactionCategory.INCOME:
            raise ValueError("Income is not an expense budget")
        return value


class TemplateInput(PlanningInput):
    id: UUID
    name: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=0)
    entries: list[TemplateEntry] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_entries(self) -> "TemplateInput":
        if len({(e.category, e.currency) for e in self.entries}) != len(self.entries):
            raise ValueError("Duplicate category and currency")
        return self


class TemplateView(TemplateInput):
    version: int


class TemplateDelete(PlanningInput):
    expected_version: int = Field(ge=1)


class TemplateTarget(PlanningInput):
    month: date
    mode: Literal["missing", "overwrite"] = "missing"

    @field_validator("month")
    @classmethod
    def month_start(cls, value: date) -> date:
        if value.day != 1 or not 1900 <= value.year <= 9998:
            raise ValueError("Expected eligible month start")
        return value


class TemplateApply(TemplateTarget):
    operation_id: UUID
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class TemplateChange(PlanningInput):
    category: TransactionCategory
    currency: str
    before: Decimal | None
    after: Decimal
    action: Literal["create", "replace", "keep"]


class TemplatePreview(TemplateTarget):
    template_id: UUID
    template_name: str
    template_version: int
    fingerprint: str
    changes: list[TemplateChange]
    applied: bool = False
