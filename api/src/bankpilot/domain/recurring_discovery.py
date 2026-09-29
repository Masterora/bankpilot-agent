"""Conservative, read-only monthly charge discovery from imported evidence."""

import calendar
import hashlib
import json
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bankpilot.domain.planning import Currency, Money

RULE_VERSION = "recurring-discovery-v1"
MERCHANT_NORMALIZATION_VERSION = "merchant-normalization-v1"
GENERIC_MERCHANTS = frozenset({"微信支付", "支付宝", "wechat pay", "alipay"})


@dataclass(frozen=True, slots=True)
class ChargeEvidence:
    booking_date: date
    amount: Decimal


def normalize_merchant(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def month_index(value: date) -> int:
    return value.year * 12 + value.month


def month_start(index: int) -> date:
    return date((index - 1) // 12, (index - 1) % 12 + 1, 1)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class DiscoveryObservation(BaseModel):
    transaction_id: UUID
    booking_date: date
    merchant: str
    amount: Decimal


class ExcludedRefundObservation(DiscoveryObservation):
    reason: Literal["confirmed_refund"] = "confirmed_refund"


class UnidentifiedRefundObservation(ExcludedRefundObservation):
    account_name: str
    currency: str


class DiscoveryGroup(BaseModel):
    key: str
    account_id: UUID
    account_name: str
    currency: str
    normalized_merchant: str
    status: Literal["candidate", "insufficient", "ambiguous", "existing"]
    reason: str
    evidence_digest: str
    observation_count: int
    observations: list[DiscoveryObservation]
    excluded_refund_count: int
    excluded_refunds: list[ExcludedRefundObservation]
    existing_plan_ids: list[UUID]
    observed_months: list[date]
    amount_min: Decimal | None
    amount_max: Decimal | None
    decision_status: Literal["active", "ignored", "linked", "created"] = "active"
    decision_version: int = 0
    decision_plan_id: UUID | None = None


class DiscoveryPage(BaseModel):
    through: date
    window_start: date
    ledger_revision: int
    rule_version: str
    merchant_normalization_version: str
    discovery_snapshot_token: str
    total: int
    offset: int
    has_more: bool
    transaction_count: int
    excluded_counts: dict[str, int]
    unidentified_refund_count: int
    unidentified_refunds: list[UnidentifiedRefundObservation]
    coverage: str
    items: list[DiscoveryGroup]


class DiscoveryDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    group_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: Literal["ignore", "restore", "link", "unlink"]
    expected_version: int = Field(ge=0)
    through: date | None = None
    evidence_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    discovery_snapshot_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    target_plan_id: UUID | None = None


class DiscoveryDecisionReceipt(BaseModel):
    operation_id: UUID
    group_key: str
    status: Literal["active", "ignored", "linked", "created"]
    version: int
    target_plan_id: UUID | None
    account_id: UUID
    currency: str
    normalized_merchant: str


class SavedDiscoveryDecision(BaseModel):
    group_key: str
    account_id: UUID
    currency: str
    normalized_merchant: str
    merchant_normalization_version: str
    status: Literal["ignored", "linked"]
    version: int
    target_plan_id: UUID | None
    evidence_status: Literal["not_checked"] = "not_checked"
    needs_review: bool = False


class DiscoveryDecisionPage(BaseModel):
    status: Literal["ignored", "linked"]
    total: int
    offset: int
    has_more: bool
    decision_snapshot_token: str
    items: list[SavedDiscoveryDecision]


class RecurringDiscoveryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    merchant: str = Field(min_length=1, max_length=160)
    account_id: UUID
    currency: Currency
    amount: Money
    cadence: Literal["monthly"]
    start_date: date

    @field_validator("start_date")
    @classmethod
    def valid_date(cls, value: date) -> date:
        if not 1900 <= value.year <= 9998:
            raise ValueError("Date out of range")
        return value


class DiscoveryProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_request_id: UUID
    group_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    through: date
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    discovery_snapshot_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_version: int = Field(ge=0)
    draft: RecurringDiscoveryDraft


class DiscoveryProposalEvidence(BaseModel):
    transaction_id: UUID
    booking_date: date
    amount: Decimal


class DiscoveryProposal(BaseModel):
    id: UUID
    proposal_request_id: UUID
    group_key: str
    through: date
    expires_at: str
    status: Literal["pending", "confirmed", "expired"]
    plan_id: UUID
    account_name: str
    draft: RecurringDiscoveryDraft | None
    evidence_digest: str
    evidence: list[DiscoveryProposalEvidence]
    receipt: DiscoveryDecisionReceipt | None


def classify(rows: Sequence[ChargeEvidence], through: date) -> tuple[str, str]:
    by_month: dict[int, int] = defaultdict(int)
    for row in rows:
        by_month[month_index(row.booking_date)] += 1
    if any(count != 1 for count in by_month.values()):
        return "ambiguous", "multiple_charges_in_month"
    ordered = sorted(rows, key=lambda row: row.booking_date)
    if len(ordered) < 3:
        return "insufficient", "fewer_than_three_months"
    recent = ordered[-3:]
    months = [month_index(row.booking_date) for row in recent]
    if months != list(range(months[0], months[0] + 3)):
        return "insufficient", "recent_months_not_consecutive"
    if month_index(through) - months[-1] > 1:
        return "insufficient", "last_charge_not_recent"
    anchor = max(row.booking_date.day for row in recent)
    if any(
        abs(
            row.booking_date.day
            - min(anchor, calendar.monthrange(row.booking_date.year, row.booking_date.month)[1])
        )
        > 3
        for row in ordered
    ):
        return "ambiguous", "charge_dates_vary"
    amounts = [abs(row.amount) for row in ordered]
    middle = median(amounts)
    if any(abs(amount - middle) > middle * Decimal("0.10") for amount in amounts):
        return "ambiguous", "amounts_vary"
    return "candidate", "three_recent_months"
