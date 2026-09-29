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

from pydantic import BaseModel

RULE_VERSION = "recurring-discovery-v1"
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


class DiscoveryPage(BaseModel):
    through: date
    window_start: date
    ledger_revision: int
    rule_version: str
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
