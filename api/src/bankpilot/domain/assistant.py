"""助手对话与工具契约：模型只能读取业务数据或提出预算修改，不能批准操作。"""

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import Currency, Money, PlanningInput
from bankpilot.domain.spending import SpendingScope


class Message(PlanningInput):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class ChatInput(PlanningInput):
    messages: list[Message] = Field(min_length=1, max_length=16)
    month: date
    locale: Literal["zh-CN", "en-US"] = "zh-CN"
    spending_context: SpendingScope | None = None

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


class ReadSpending(PlanningInput):
    kind: Literal["spending"]
    arguments: SpendingScope


class ProposeBudget(PlanningInput):
    kind: Literal["propose_budget"]
    arguments: BudgetArguments


class Answer(PlanningInput):
    kind: Literal["answer"]
    text: str = Field(min_length=1, max_length=3000)


Decision = Annotated[
    ReadBudgets | ReadRecurring | ReadOverview | ReadSpending | ProposeBudget | Answer,
    Field(discriminator="kind"),
]
decision_adapter: TypeAdapter[Decision] = TypeAdapter(Decision)


class ActionInput(PlanningInput):
    id: UUID


class TurnInput(MonthArguments):
    protocol_version: Literal[2]
    request_id: UUID
    creation_id: UUID | None = None
    conversation_id: UUID | None = None
    question: str = Field(min_length=1, max_length=1000)
    locale: Literal["zh-CN", "en-US"] = "zh-CN"
    spending_context: SpendingScope | None = None
    retry_of: UUID | None = None

    @model_validator(mode="after")
    def target(self) -> "TurnInput":
        if (self.creation_id is None) == (self.conversation_id is None):
            raise ValueError("Provide one conversation identity")
        if not self.question.strip():
            raise ValueError("Question cannot be blank")
        return self


class ScopeInput(MonthArguments):
    spending_context: SpendingScope | None = None


class TurnView(PlanningInput):
    id: UUID
    conversation_id: UUID
    request_id: UUID
    sequence: int
    question: str
    month: date
    scope: SpendingScope | None
    status: Literal["processing", "completed", "failed"]
    created_at: datetime
    completed_at: datetime | None
    result_version: int
    reply: dict[str, Any] | None
    error_code: str | None


class ConversationView(PlanningInput):
    id: UUID
    title: str
    month: date
    scope: SpendingScope | None
    created_at: datetime
    updated_at: datetime


class ConversationPage(PlanningInput):
    items: list[ConversationView]
    next_cursor: UUID | None
    recent_id: UUID | None


class ConversationDetail(PlanningInput):
    conversation: ConversationView
    turns: list[TurnView]
    next_before: int | None
    turn_limit: int
