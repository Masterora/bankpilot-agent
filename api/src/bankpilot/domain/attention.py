"""Deterministic contracts and projection rules for persisted attention items."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

ATTENTION_RULE_VERSION = "attention-v1"
BUSINESS_ZONE = ZoneInfo("Asia/Shanghai")


class AttentionType(StrEnum):
    BUDGET_NEAR_LIMIT = "budget_near_limit"
    BUDGET_LIMIT_REACHED = "budget_limit_reached"
    BUDGET_OVERSPENT = "budget_overspent"
    RECURRING_UPCOMING = "recurring_upcoming"
    RECURRING_UNREVIEWED = "recurring_unreviewed"
    RECURRING_REVIEW_REQUIRED = "recurring_review_required"


class AttentionSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: Literal["budget", "recurring"]
    source_id: UUID
    source_date: date


class AttentionStateInput(AttentionSource):
    operation_id: UUID
    action: Literal["read", "snooze", "restore"]
    fact_token: str = Field(min_length=64, max_length=64)
    expected_state_version: str = Field(min_length=3, max_length=80)
    snooze_option: Literal["two_hours", "tomorrow_09", "seven_days_09"] | None = None


class AttentionPreferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    enabled: bool
    expected_version: int = Field(ge=0)


class AttentionPreference(BaseModel):
    attention_type: AttentionType
    enabled: bool
    version: int


class AttentionItem(BaseModel):
    source: AttentionSource
    attention_type: AttentionType
    state: Literal["unread", "read", "snoozed"]
    fact_token: str
    state_version: str
    title: str
    category: str | None = None
    currency: str
    amount: Decimal
    current_amount: Decimal | None = None
    snoozed_until: datetime | None = None
    tracking_gap: dict[str, str] | None = None


class AttentionGroup(BaseModel):
    status: Literal["ready", "unavailable"]
    code: str | None = None
    retryable: bool = False
    read_at: datetime
    unread: list[AttentionItem] = Field(default_factory=list)
    read: list[AttentionItem] = Field(default_factory=list)
    snoozed: list[AttentionItem] = Field(default_factory=list)
    disabled_count: int = 0
    preferences: list[AttentionPreference] = Field(default_factory=list)


class AttentionResponse(BaseModel):
    month: date
    server_time: datetime
    next_refresh_at: datetime
    budgets: AttentionGroup | None = None
    recurring: AttentionGroup | None = None


class AttentionReceipt(BaseModel):
    operation_id: UUID
    accepted_version: str
    snoozed_until: datetime | None = None


@dataclass(frozen=True)
class AttentionFact:
    source_type: Literal["budget", "recurring"]
    source_id: UUID
    source_date: date
    attention_type: AttentionType | None
    title: str
    category: str | None
    currency: str
    amount: Decimal
    current_amount: Decimal | None

    @property
    def active(self) -> bool:
        return self.attention_type is not None

    @property
    def signature(self) -> str:
        # Display-only values intentionally do not reopen a previously handled item.
        payload = {
            "active": self.active,
            "attention_type": self.attention_type,
            "rule": ATTENTION_RULE_VERSION,
        }
        return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


@dataclass(frozen=True)
class AttentionState:
    """Pure handling state; shared by GET projection and transactional persistence."""

    generation: int
    revision: int
    state: str
    snoozed_until: datetime | None
    fact_status: str
    fact_signature: str
    attention_type: str
    state_attention_type: str | None
    unknown_reason: str | None = None
    unknown_since: datetime | None = None
    last_tracking_gap: dict[str, str] | None = None
    expired: bool = False


def project_attention(
    row: AttentionState | None, fact: AttentionFact | None, now: datetime
) -> AttentionState:
    if row is None:
        if fact is None or fact.attention_type is None:
            raise ValueError("Only active facts can create handling state")
        return AttentionState(
            1, 0, "unread", None, "active", fact.signature, fact.attention_type.value, None
        )
    if fact is None:
        if row.fact_status == "unknown":
            return row
        return replace(
            row,
            fact_status="unknown",
            generation=row.generation + 1,
            revision=row.revision + 1,
            state="unread",
            snoozed_until=None,
            state_attention_type=None,
            unknown_reason="attention_capacity",
            unknown_since=now,
            expired=False,
        )
    gap = row.last_tracking_gap
    if row.fact_status == "unknown":
        gap = {
            "reason": row.unknown_reason or "attention_capacity",
            "started_at": row.unknown_since.isoformat() if row.unknown_since else "unknown",
            "ended_at": now.isoformat(),
        }
    if not fact.active:
        changed = row.fact_status != "inactive" or row.fact_signature != fact.signature
        return replace(
            row,
            fact_status="inactive",
            fact_signature=fact.signature,
            generation=row.generation + int(row.fact_status == "unknown"),
            revision=row.revision + int(changed),
            state="unread" if changed else row.state,
            snoozed_until=None if changed else row.snoozed_until,
            state_attention_type=None if changed else row.state_attention_type,
            unknown_reason=None,
            unknown_since=None,
            last_tracking_gap=gap,
            expired=False,
        )
    kind = str(fact.attention_type)
    reopened = (
        row.fact_status != "active"
        or row.fact_signature != fact.signature
        or row.attention_type != kind
        or row.state_attention_type not in (None, kind)
    )
    state, snoozed = ("unread", None) if reopened else (row.state, row.snoozed_until)
    expired = state == "snoozed" and snoozed is not None and snoozed <= now
    if expired:
        state, snoozed = "unread", None
    return replace(
        row,
        generation=row.generation + int(reopened),
        revision=row.revision + int(reopened) + int(expired),
        state=state,
        snoozed_until=snoozed,
        fact_status="active",
        fact_signature=fact.signature,
        attention_type=kind,
        state_attention_type=kind if state != "unread" else None,
        unknown_reason=None,
        unknown_since=None,
        last_tracking_gap=gap,
        expired=expired,
    )


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def fact_token(user_id: UUID, fact: AttentionFact, generation: int) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "user_id": user_id,
                "source_type": fact.source_type,
                "source_id": fact.source_id,
                "source_date": fact.source_date,
                "generation": generation,
                "attention_type": fact.attention_type,
                "rule": ATTENTION_RULE_VERSION,
            }
        ).encode()
    ).hexdigest()


def state_version(revision: int, *, expired: bool = False) -> str:
    return f"{revision}:{'expired' if expired else 'current'}"


def snooze_deadline(option: str, now: datetime) -> datetime:
    local = now.astimezone(BUSINESS_ZONE)
    if option == "two_hours":
        return now.astimezone(UTC) + timedelta(hours=2)
    days = 1 if option == "tomorrow_09" else 7
    target_date = local.date() + timedelta(days=days)
    if not 1900 <= target_date.year <= 9998:
        raise ValueError("invalid_snooze_time")
    return datetime.combine(
        target_date, datetime.min.time().replace(hour=9), BUSINESS_ZONE
    ).astimezone(UTC)


AttentionGroupName = Annotated[Literal["all", "budgets", "recurring"], Field()]
