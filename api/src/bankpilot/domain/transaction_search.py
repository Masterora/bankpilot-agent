"""
文件职责：定义有界原始账本搜索与核查投影契约。
主要内容：文本标准化、日期账户币种及绝对金额过滤、分页与导出版本、详情和核查响应。
关键边界：范围与容量显式受限；金额条件使用指定币种的十进制绝对值，用户身份不由过滤条件提供。
"""
import re
import unicodedata
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from bankpilot.domain.contracts import ReviewItem, TransactionCategory, TransactionItem
from bankpilot.domain.planning import Currency, PlanningInput

SEARCH_VERSION = "search-v1"
PAGE_SIZE = 20
CAPACITY = 10_000


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class SearchFilters(PlanningInput):
    start_date: date
    end_date: date
    account_id: UUID | None = None
    currency: Currency | None = None
    direction: Literal["all", "debit", "credit"] = "all"
    min_amount: str | None = None
    max_amount: str | None = None
    text: str = Field(default="", max_length=100)
    text_scope: Literal["merchant", "merchant_or_note"] = "merchant_or_note"
    category: TransactionCategory | None = None
    import_batch_id: UUID | None = None

    @field_validator("text")
    @classmethod
    def normalized(cls, value: str) -> str:
        result = normalize_text(value)
        if len(result) > 100:
            raise ValueError("Text exceeds limit")
        return result

    @field_validator("min_amount", "max_amount")
    @classmethod
    def amount(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[0-9]{1,16}(?:\.[0-9]{1,2})?", value):
            raise ValueError("Use a non-negative decimal string with at most two decimal places")
        return format(Decimal(value), ".2f")

    @model_validator(mode="after")
    def valid_filters(self) -> "SearchFilters":
        if self.end_date < self.start_date or (self.end_date - self.start_date).days > 366:
            raise ValueError("Select an ordered period of at most 366 days")
        if (self.min_amount is not None or self.max_amount is not None) and not self.currency:
            raise ValueError("Amount requires currency")
        if self.min_amount is not None and self.max_amount is not None:
            if Decimal(self.min_amount) > Decimal(self.max_amount):
                raise ValueError("Minimum exceeds maximum")
        return self


class SearchVersion(PlanningInput):
    expected_revision: int | None = Field(default=None, ge=0)
    expected_search_version: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def paired(self) -> "SearchVersion":
        if (self.expected_revision is None) != (self.expected_search_version is None):
            raise ValueError("Both versions are required together")
        return self


class SearchRequest(SearchVersion):
    filters: SearchFilters
    offset: int = Field(default=0, ge=0, le=CAPACITY, multiple_of=PAGE_SIZE)

    @model_validator(mode="after")
    def page_version(self) -> "SearchRequest":
        if self.offset and self.expected_revision is None:
            raise ValueError("Paging requires versions")
        return self


class SearchExport(PlanningInput):
    filters: SearchFilters
    expected_revision: int = Field(ge=0)
    expected_search_version: str = Field(max_length=50)


class SearchItem(TransactionItem):
    account_id: UUID
    relation_kinds: list[str] = Field(default_factory=list)


class SearchDetail(PlanningInput):
    item: SearchItem
    ledger_revision: int
    search_version: str = SEARCH_VERSION


class SearchPage(PlanningInput):
    filters: SearchFilters
    total_count: int
    items: list[SearchItem]
    offset: int
    has_more: bool
    ledger_revision: int
    search_version: str = SEARCH_VERSION


class ReviewProjectionRequest(PlanningInput):
    start_date: date
    end_date: date
    transaction_ids: list[UUID] = Field(min_length=1, max_length=20)
    expected_revision: int = Field(ge=0)
    offset: int = Field(default=0, ge=0, multiple_of=20)
    evidence_key: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evidence_offset: int = Field(default=0, ge=0, multiple_of=20)

    @model_validator(mode="after")
    def valid_period(self) -> "ReviewProjectionRequest":
        SearchFilters(start_date=self.start_date, end_date=self.end_date)
        return self


class ProjectedReview(PlanningInput):
    review: ReviewItem
    evidence: list[SearchItem]
    evidence_total: int
    evidence_offset: int


class ReviewProjection(PlanningInput):
    items: list[ProjectedReview]
    total_count: int
    offset: int
    ledger_revision: int
