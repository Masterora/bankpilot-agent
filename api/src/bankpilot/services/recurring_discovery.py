"""Read a complete user-scoped discovery snapshot before paginating groups."""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import TransactionRecord
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.domain.recurring_discovery import (
    GENERIC_MERCHANTS,
    RULE_VERSION,
    ChargeEvidence,
    DiscoveryGroup,
    DiscoveryObservation,
    DiscoveryPage,
    ExcludedRefundObservation,
    UnidentifiedRefundObservation,
    classify,
    digest,
    month_index,
    month_start,
    normalize_merchant,
)
from bankpilot.errors import PlanningError


async def discover(
    session: AsyncSession,
    user_id: UUID,
    ledger_revision: int,
    through: date,
    offset: int,
    expected_token: str | None,
) -> DiscoveryPage:
    repo = PlanningRepository(session)
    start = month_start(month_index(through) - 11)
    end = date.fromordinal(month_start(month_index(through) + 1).toordinal() - 1)
    loaded = await repo.transactions(user_id, start_date=start, end_date=end)
    if len(loaded) > 10_000:
        raise PlanningError("discovery_capacity", 422)
    rows = [row for row, _, _ in loaded]
    ids = {row.id for row in rows}
    relations = await repo.relations(user_id, ids, limit=10_001) if ids else []
    if len(relations) > 10_000:
        raise PlanningError("discovery_capacity", 422)
    excluded: set[UUID] = set()
    refunded: set[UUID] = set()
    relation_evidence: dict[UUID, list[tuple[str, str, str, str, int]]] = {}
    for relation in relations:
        reference = (
            str(relation.id),
            relation.kind,
            str(relation.first_id),
            str(relation.second_id),
            relation.version,
        )
        for identity in (relation.first_id, relation.second_id):
            if identity in ids:
                relation_evidence.setdefault(identity, []).append(reference)
        if relation.kind == "duplicate":
            excluded.add(relation.second_id)
        elif relation.kind == "transfer":
            excluded.update((relation.first_id, relation.second_id))
        elif relation.kind == "refund":
            refunded.add(relation.first_id)
    matches = await repo.discovery_matches(user_id, ids) if ids else []
    linked = {match.transaction_id for match in matches}
    counts = {
        "not_imported": 0,
        "not_charge": 0,
        "relationship": 0,
        "refunded": 0,
        "merchant_unknown": 0,
    }
    grouped: dict[tuple[UUID, str, str], list[TransactionRecord]] = {}
    refunded_groups: dict[tuple[UUID, str, str], list[TransactionRecord]] = {}
    unidentified_refunds: list[UnidentifiedRefundObservation] = []
    names: dict[UUID, str] = {}
    for row, account_name, _ in loaded:
        if row.import_batch_id is None:
            counts["not_imported"] += 1
        elif row.amount >= 0:
            counts["not_charge"] += 1
        elif row.id in excluded:
            counts["relationship"] += 1
        else:
            is_refunded = row.id in refunded
            if is_refunded:
                counts["refunded"] += 1
            merchant = normalize_merchant(row.merchant)
            if not merchant or merchant in GENERIC_MERCHANTS:
                if is_refunded:
                    unidentified_refunds.append(
                        UnidentifiedRefundObservation(
                            transaction_id=row.id,
                            booking_date=row.booking_date,
                            merchant=row.merchant,
                            amount=row.amount,
                            account_name=account_name,
                            currency=row.currency,
                        )
                    )
                else:
                    counts["merchant_unknown"] += 1
                continue
            key = (row.account_id, row.currency, merchant)
            names[row.account_id] = account_name
            if is_refunded:
                refunded_groups.setdefault(key, []).append(row)
            else:
                grouped.setdefault(key, []).append(row)
    plans = await repo.plans(user_id)
    revisions = await repo.revisions(user_id)
    plan_keys: dict[tuple[UUID, str, str], set[UUID]] = {}
    for plan in plans:
        for account_id, currency, merchant in [
            (plan.account_id, plan.currency, plan.merchant),
            *(
                (revision.account_id, revision.currency, revision.merchant)
                for revision in revisions
                if revision.plan_id == plan.id
            ),
        ]:
            key = (account_id, currency, normalize_merchant(merchant))
            plan_keys.setdefault(key, set()).add(plan.id)
    groups: list[DiscoveryGroup] = []
    for key in grouped.keys() | refunded_groups.keys():
        account_id, currency, merchant = key
        members = grouped.get(key, [])
        refunded_members = refunded_groups.get(key, [])
        members.sort(key=lambda row: (row.booking_date, str(row.id)))
        refunded_members.sort(key=lambda row: (row.booking_date, str(row.id)))
        group_key = digest([str(user_id), str(account_id), currency, merchant])
        status, reason = (
            classify([ChargeEvidence(row.booking_date, row.amount) for row in members], through)
            if members
            else ("insufficient", "all_observations_refunded")
        )
        existing = sorted(plan_keys.get(key, set()), key=str)
        if existing or any(row.id in linked for row in members):
            status, reason = "existing", "existing_plan_or_match"
        evidence = [
            ["valid", str(row.id), row.booking_date.isoformat(), str(row.amount), row.merchant]
            for row in members
        ] + [
            [
                "confirmed_refund",
                str(row.id),
                row.booking_date.isoformat(),
                str(row.amount),
                row.merchant,
            ]
            for row in refunded_members
        ]
        references = sorted(
            {
                reference
                for row in members + refunded_members
                for reference in relation_evidence.get(row.id, [])
            }
        )
        groups.append(
            DiscoveryGroup(
                key=group_key,
                account_id=account_id,
                account_name=names[account_id],
                currency=currency,
                normalized_merchant=merchant,
                status=status,
                reason=reason,
                evidence_digest=digest([RULE_VERSION, group_key, evidence, references]),
                observation_count=len(members),
                observations=[
                    DiscoveryObservation(
                        transaction_id=row.id,
                        booking_date=row.booking_date,
                        merchant=row.merchant,
                        amount=row.amount,
                    )
                    for row in members[-12:]
                ],
                excluded_refund_count=len(refunded_members),
                excluded_refunds=[
                    ExcludedRefundObservation(
                        transaction_id=row.id,
                        booking_date=row.booking_date,
                        merchant=row.merchant,
                        amount=row.amount,
                    )
                    for row in refunded_members[-12:]
                ],
                existing_plan_ids=existing,
                observed_months=sorted(
                    {month_start(month_index(row.booking_date)) for row in members}
                ),
                amount_min=min((abs(row.amount) for row in members), default=None),
                amount_max=max((abs(row.amount) for row in members), default=None),
            )
        )
    groups.sort(
        key=lambda group: (
            -max(o.booking_date.toordinal() for o in group.observations + group.excluded_refunds),
            group.key,
        )
    )
    unidentified_refunds.sort(key=lambda row: (row.booking_date, str(row.transaction_id)))
    token = digest(
        [
            RULE_VERSION,
            ledger_revision,
            through.isoformat(),
            sorted(
                (str(r.id), r.kind, str(r.first_id), str(r.second_id), r.version) for r in relations
            ),
            sorted(
                (str(match.plan_id), match.due_date.isoformat(), str(match.transaction_id))
                for match in matches
            ),
            sorted(
                (
                    str(p.id),
                    p.version,
                    p.status,
                    str(p.account_id),
                    p.currency,
                    p.merchant,
                    p.start_date.isoformat(),
                )
                for p in plans
            ),
            sorted(
                (
                    str(r.plan_id),
                    r.effective_month.isoformat(),
                    str(r.account_id),
                    r.currency,
                    r.merchant,
                    str(r.amount),
                    r.cadence,
                    r.start_date.isoformat(),
                )
                for r in revisions
            ),
            counts,
            [
                (str(row.transaction_id), row.booking_date.isoformat(), str(row.amount))
                for row in unidentified_refunds
            ],
            [
                (
                    group.key,
                    group.account_name,
                    group.status,
                    group.evidence_digest,
                    group.excluded_refund_count,
                    [str(identity) for identity in group.existing_plan_ids],
                )
                for group in groups
            ],
        ]
    )
    if expected_token is not None and token != expected_token:
        raise PlanningError("discovery_evidence_stale", 409)
    return DiscoveryPage(
        through=through,
        window_start=start,
        ledger_revision=ledger_revision,
        rule_version=RULE_VERSION,
        discovery_snapshot_token=token,
        total=len(groups),
        offset=offset,
        has_more=offset + 20 < len(groups),
        transaction_count=len(rows),
        excluded_counts=counts,
        unidentified_refund_count=len(unidentified_refunds),
        unidentified_refunds=unidentified_refunds[-12:],
        coverage="unverified_import_coverage",
        items=groups[offset : offset + 20],
    )
