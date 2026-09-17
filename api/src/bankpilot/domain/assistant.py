"""助手对话与工具契约：模型只能读取业务数据或提出预算修改，不能批准操作。"""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import Currency, Money, PlanningInput


class Message(PlanningInput):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class ChatInput(PlanningInput):
    messages: list[Message] = Field(min_length=1, max_length=16)
    month: date
    locale: Literal["zh-CN", "en-US"] = "zh-CN"

    @model_validator(mode="after")
    def user_turn(self) -> "ChatInput":
        if self.messages[-1].role != "user" or not 1900 <= self.month.year <= 9998:
            raise ValueError("Invalid conversation or month")
        return self


class MonthArguments(PlanningInput):
    month: date

    @model_validator(mode="after")
    def valid_month(self) -> "MonthArguments":
        if not 1900 <= self.month.year <= 9998 or self.month.day != 1:
            raise ValueError("Month must be first day, year 1900..9998")
        return self


class BudgetArguments(MonthArguments):
    category: TransactionCategory
    currency: Currency
    amount: Money

    @field_validator("category")
    @classmethod
    def expense_only(cls, value: TransactionCategory) -> TransactionCategory:
        if value == TransactionCategory.INCOME:
            raise ValueError("Income cannot have an expense budget")
        return value


class ReadBudgets(PlanningInput):
    kind: Literal["budgets"]
    arguments: MonthArguments


class ReadRecurring(PlanningInput):
    kind: Literal["recurring"]
    arguments: MonthArguments


class ReadOverview(PlanningInput):
    kind: Literal["overview"]
    arguments: MonthArguments


class ProposeBudget(PlanningInput):
    kind: Literal["propose_budget"]
    arguments: BudgetArguments


class Answer(PlanningInput):
    kind: Literal["answer"]
    text: str = Field(min_length=1, max_length=3000)


Decision = Annotated[
    ReadBudgets | ReadRecurring | ReadOverview | ProposeBudget | Answer,
    Field(discriminator="kind"),
]
decision_adapter: TypeAdapter[Decision] = TypeAdapter(Decision)


class ActionInput(PlanningInput):
    id: UUID
