"""Compare frozen report facts with Decimal arithmetic and explicit provenance."""

import json
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from bankpilot.domain.reports import MonthlySnapshot


class ComparisonMetric(BaseModel):
    section: str
    key: str
    currency: str | None = None
    field: str
    before: Decimal
    after: Decimal
    delta: Decimal


class ComparisonChange(BaseModel):
    section: str
    key: str
    kind: Literal["added", "removed", "changed"]
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class ReportComparison(BaseModel):
    before_id: UUID
    after_id: UUID
    before: dict[str, Any]
    after: dict[str, Any]
    same_month: bool
    same_rules: bool
    metrics: list[ComparisonMetric]
    changes: list[ComparisonChange]


def compare_reports(
    before_id: UUID, after_id: UUID, before: MonthlySnapshot, after: MonthlySnapshot
) -> ReportComparison:
    metrics: list[ComparisonMetric] = []
    changes: list[ComparisonChange] = []

    def aggregate(
        section: str,
        old: list[dict[str, Any]],
        new: list[dict[str, Any]],
        keys: list[str],
        fields: list[str],
    ) -> None:
        def index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
            return {":".join(str(row[k]) for k in keys): row for row in rows}

        left, right = index(old), index(new)
        for key in sorted(left.keys() | right.keys()):
            a, b = left.get(key, {}), right.get(key, {})
            for field in fields:
                first, second = Decimal(str(a.get(field, 0))), Decimal(str(b.get(field, 0)))
                metrics.append(
                    ComparisonMetric(
                        section=section,
                        key=key,
                        currency=(a or b).get("currency"),
                        field=field,
                        before=first,
                        after=second,
                        delta=second - first,
                    )
                )

    def differences(
        section: str, old: list[dict[str, Any]], new: list[dict[str, Any]], keys: list[str]
    ) -> None:
        def index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
            return {json.dumps([r.get(k) for k in keys], sort_keys=True): r for r in rows}

        left, right = index(old), index(new)
        for key in sorted(left.keys() | right.keys()):
            a, b = left.get(key), right.get(key)
            if a != b:
                changes.append(
                    ComparisonChange(
                        section=section,
                        key=key,
                        kind="added" if a is None else "removed" if b is None else "changed",
                        before=a,
                        after=b,
                    )
                )

    old, new = before.model_dump(mode="json"), after.model_dump(mode="json")
    aggregate(
        "raw",
        old["analysis"]["currency_summaries"],
        new["analysis"]["currency_summaries"],
        ["currency"],
        ["income", "expense", "net", "transaction_count"],
    )
    aggregate(
        "adjusted",
        old["review"]["adjusted_summaries"],
        new["review"]["adjusted_summaries"],
        ["currency"],
        [
            "raw_inflow",
            "raw_outflow",
            "adjusted_inflow",
            "adjusted_outflow",
            "adjusted_net",
            "duplicate_excluded",
            "transfer_excluded",
            "refund_amount",
        ],
    )
    aggregate(
        "category",
        old["analysis"]["category_summaries"],
        new["analysis"]["category_summaries"],
        ["currency", "category"],
        ["amount", "transaction_count"],
    )
    aggregate(
        "coverage",
        [old["review"]["coverage"]],
        [new["review"]["coverage"]],
        [],
        ["transaction_count", "import_batch_count"],
    )
    differences("transactions", old["transactions"]["items"], new["transactions"]["items"], ["id"])
    differences(
        "relations",
        old["review"]["relations"],
        new["review"]["relations"],
        ["kind", "first_id", "second_id"],
    )
    differences("evidence", old["review"]["evidence"], new["review"]["evidence"], ["id"])
    differences(
        "anomalies",
        old["analysis"]["anomalies"],
        new["analysis"]["anomalies"],
        ["rule_id", "transaction_ids"],
    )

    def provenance(snapshot: MonthlySnapshot) -> dict[str, Any]:
        return {
            "month": str(snapshot.month),
            "ledger_revision": snapshot.ledger_revision,
            "report_rule_version": snapshot.report_rule_version,
            "relation_rule_version": snapshot.review.rule_version,
            "snapshot_at": snapshot.review.snapshot_at.isoformat(),
            "coverage": snapshot.review.coverage.model_dump(mode="json"),
            "candidates_truncated": snapshot.review.candidates_truncated,
        }

    return ReportComparison(
        before_id=before_id,
        after_id=after_id,
        before=provenance(before),
        after=provenance(after),
        same_month=before.month == after.month,
        same_rules=(before.report_rule_version, before.review.rule_version)
        == (after.report_rule_version, after.review.rule_version),
        metrics=metrics,
        changes=changes,
    )
