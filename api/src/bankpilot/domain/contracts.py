"""
文件职责：定义工作流、卡片、账单分析、适配器与应用层共用的领域契约。

主要内容：
- `RunStatus`：Agent 运行的持久化状态集。
- `CardStatus`：卡片可被展示和后续状态操作使用的稳定状态集。
- `TransactionQuery`：受限的交易日期范围。
- `SupportedAction` / `UnsupportedIntent`：模型规划决策的可辨别联合。
- `ModelPlan`：模型决策、供应商、耗时和 Token 用量。
- `TransactionCategory`：稳定的账单分类代码。
- `TransactionResult` / `BillAnalysis` / `RunResult`：查询、统计与工作流结果结构。

关键边界：模型只能产生白名单动作或不支持意图；交易查询最长 366 天。
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunStatus(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class CardStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"


class TransactionCategory(StrEnum):
    INCOME = "income"
    GROCERIES = "groceries"
    DINING = "dining"
    TRANSPORT = "transport"
    SHOPPING = "shopping"
    HOUSING = "housing"
    UTILITIES = "utilities"
    ENTERTAINMENT = "entertainment"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    TRAVEL = "travel"
    TRANSFER = "transfer"
    OTHER = "other"


class CategorySource(StrEnum):
    RULE = "rule"
    USER = "user"


class TransactionQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_period(self) -> "TransactionQuery":
        """保证模型选择的查询时间有序，且不超出可控运行范围。"""
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if (self.end_date - self.start_date).days > 366:
            raise ValueError("date range must not exceed 366 days")
        return self


class DraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["query_transactions"]
    arguments: TransactionQuery
    user_message: str = Field(min_length=1, max_length=300)


class UnsupportedIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["unsupported"]
    user_message: str = Field(min_length=1, max_length=300)


class SupportedAction(DraftAction):
    kind: Literal["action"]


PlanningDecision = Annotated[SupportedAction | UnsupportedIntent, Field(discriminator="kind")]


class ModelUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ModelPlan(BaseModel):
    decision: PlanningDecision
    provider: str
    model: str
    request_id: str | None = None
    latency_ms: int
    usage: ModelUsage = Field(default_factory=ModelUsage)


class TransactionItem(BaseModel):
    id: UUID
    time_precision: Literal["unknown", "date", "timestamp"] = "unknown"
    import_batch_id: UUID | None = None
    source_row_number: int | None = None
    booking_date: date
    occurred_at: datetime
    merchant: str
    description: str
    amount: Decimal
    currency: str
    account_name: str
    category: TransactionCategory = TransactionCategory.OTHER
    category_source: CategorySource = CategorySource.RULE
    category_rule_id: str = "category_other_v1"


class TransactionResult(BaseModel):
    start_date: date
    end_date: date
    items: list[TransactionItem]


class CurrencySummary(BaseModel):
    currency: str
    income: Decimal
    expense: Decimal
    net: Decimal
    transaction_count: int


class CategorySummary(BaseModel):
    category: TransactionCategory
    currency: str
    amount: Decimal
    transaction_count: int


class BillAnomaly(BaseModel):
    rule_id: Literal["large_outflow_v1", "possible_duplicate_v1"]
    severity: Literal["notice", "warning"]
    transaction_ids: list[UUID]
    facts: dict[str, str]


class BillAnalysis(BaseModel):
    currency_summaries: list[CurrencySummary] = Field(default_factory=list)
    category_summaries: list[CategorySummary] = Field(default_factory=list)
    anomalies: list[BillAnomaly] = Field(default_factory=list)


class RunResult(BaseModel):
    message: str
    transactions: TransactionResult
    analysis: BillAnalysis = Field(default_factory=BillAnalysis)
