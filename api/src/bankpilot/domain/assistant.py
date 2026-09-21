"""
文件职责：定义助手对话、工具调用、上下文与提案契约。
主要内容：消费和账本搜索工具参数、预算提案、会话轮次视图、独立搜索上下文及版本化更新输入。
关键边界：模型只能读取或提出修改，不能批准写入；用户归属由服务端身份决定。
"""
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import Currency, Money, PlanningInput
from bankpilot.domain.spending import SpendingScope
from bankpilot.domain.transaction_search import SearchFilters


class Message(PlanningInput):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class ChatInput(PlanningInput):
    messages: list[Message] = Field(min_length=1, max_length=16)
    month: date
    locale: Literal["zh-CN", "en-US"] = "zh-CN"
    spending_context: SpendingScope | None = None
    search_context: SearchFilters | None = None

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


class FindArguments(SearchFilters):
    account_name: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def single_account(self) -> "FindArguments":
        if self.account_name and self.account_id:
            raise ValueError("Provide account name or ID, not both")
        return self


class FindTransactions(PlanningInput):
    kind: Literal["find_transactions"]
    arguments: FindArguments


class ProposeBudget(PlanningInput):
    kind: Literal["propose_budget"]
    arguments: BudgetArguments


class Answer(PlanningInput):
    kind: Literal["answer"]
    text: str = Field(min_length=1, max_length=3000)


Decision = Annotated[
    ReadBudgets
    | ReadRecurring
    | ReadOverview
    | ReadSpending
    | FindTransactions
    | ProposeBudget
    | Answer,
    Field(discriminator="kind"),
]
decision_adapter: TypeAdapter[Decision] = TypeAdapter(Decision)


class ActionInput(PlanningInput):
    id: UUID


class TurnInput(MonthArguments):
    protocol_version: Literal[3]
    expected_context_version: int = Field(ge=0)
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


class SearchContextInput(PlanningInput):
    filters: SearchFilters | None
    expected_context_version: int = Field(ge=0)


class ScopeInput(MonthArguments):
    expected_context_version: int = Field(ge=0)
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
    search_context: SearchFilters | None
    context_version: int
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
