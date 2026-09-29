"""Read a complete user-scoped discovery snapshot before paginating groups."""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.discovery_repository import DiscoveryRepository
from bankpilot.db.models import (
    RecurringDiscoveryDecisionRecord,
    RecurringDiscoveryOperationRecord,
    TransactionRecord,
    UserRecord,
)
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.recurring_discovery import (
    GENERIC_MERCHANTS,
    MERCHANT_NORMALIZATION_VERSION,
    RULE_VERSION,
    ChargeEvidence,
    DiscoveryDecisionInput,
    DiscoveryDecisionPage,
    DiscoveryDecisionReceipt,
    DiscoveryGroup,
    DiscoveryObservation,
    DiscoveryPage,
    ExcludedRefundObservation,
    SavedDiscoveryDecision,
    UnidentifiedRefundObservation,
    classify,
    digest,
    month_index,
    month_start,
    normalize_merchant,
)
from bankpilot.errors import PlanningError
from bankpilot.services.planning_reads import effective_config, planning_today


async def discover(
    session: AsyncSession,
    user_id: UUID,
    ledger_revision: int,
    through: date,
    offset: int,
    expected_token: str | None,
    *,
    all_groups: bool = False,
) -> DiscoveryPage:
    repo = PlanningRepository(session)
    decisions = await DiscoveryRepository(session).decisions(user_id)
    _check_normalization(decisions)
    by_key = {row.group_key: row for row in decisions}
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
                decision_status=by_key[group_key].status if group_key in by_key else "active",
                decision_version=by_key[group_key].version if group_key in by_key else 0,
                decision_plan_id=by_key[group_key].target_plan_id if group_key in by_key else None,
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
            MERCHANT_NORMALIZATION_VERSION,
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
                    str(p.amount),
                    p.cadence,
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
            sorted(
                (row.group_key, row.status, row.version, str(row.target_plan_id))
                for row in decisions
            ),
        ]
    )
    if expected_token is not None and token != expected_token:
        raise PlanningError("discovery_evidence_stale", 409)
    active = [group for group in groups if group.decision_status == "active"]
    return DiscoveryPage(
        through=through,
        window_start=start,
        ledger_revision=ledger_revision,
        rule_version=RULE_VERSION,
        merchant_normalization_version=MERCHANT_NORMALIZATION_VERSION,
        discovery_snapshot_token=token,
        total=len(active),
        offset=offset,
        has_more=offset + 20 < len(active),
        transaction_count=len(rows),
        excluded_counts=counts,
        unidentified_refund_count=len(unidentified_refunds),
        unidentified_refunds=unidentified_refunds[-12:],
        coverage="unverified_import_coverage",
        items=groups if all_groups else active[offset : offset + 20],
    )


def _check_normalization(rows: list[RecurringDiscoveryDecisionRecord]) -> None:
    if any(row.merchant_normalization_version != MERCHANT_NORMALIZATION_VERSION for row in rows):
        raise PlanningError("discovery_normalization_conflict", 409)


async def saved_decisions(
    session: AsyncSession, user_id: UUID, status: str, offset: int, expected_token: str | None
) -> DiscoveryDecisionPage:
    rows = await DiscoveryRepository(session).decisions(user_id)
    _check_normalization(rows)
    plans = {plan.id: plan for plan in await PlanningRepository(session).plans(user_id)}
    revisions = await PlanningRepository(session).revisions(user_id)
    relevant = sorted(
        (row for row in rows if row.status == status),
        key=lambda row: (-row.updated_at.timestamp(), row.group_key),
    )
    token = digest(
        [
            MERCHANT_NORMALIZATION_VERSION,
            sorted(
                (row.group_key, row.status, row.version, str(row.target_plan_id)) for row in rows
            ),
            sorted(
                (
                    str(plan.id),
                    plan.version,
                    plan.status,
                    str(plan.account_id),
                    plan.currency,
                    plan.merchant,
                    str(plan.amount),
                    plan.cadence,
                    plan.start_date.isoformat(),
                )
                for plan in plans.values()
            ),
            sorted(
                (
                    str(row.plan_id),
                    row.effective_month.isoformat(),
                    str(row.account_id),
                    row.currency,
                    row.merchant,
                    str(row.amount),
                    row.cadence,
                    row.start_date.isoformat(),
                )
                for row in revisions
            ),
        ]
    )
    if expected_token is not None and token != expected_token:
        raise PlanningError("discovery_evidence_stale", 409)
    items = []
    for row in relevant[offset : offset + 20]:
        plan = plans.get(row.target_plan_id) if row.target_plan_id else None
        config = effective_config(plan, revisions, planning_today()) if plan else None
        needs_review = bool(
            row.status == "linked"
            and (
                config is None
                or config.account_id != row.account_id
                or config.currency != row.currency
                or normalize_merchant(config.merchant) != row.normalized_merchant
            )
        )
        items.append(
            SavedDiscoveryDecision(
                group_key=row.group_key,
                account_id=row.account_id,
                currency=row.currency,
                normalized_merchant=row.normalized_merchant,
                merchant_normalization_version=row.merchant_normalization_version,
                status=row.status,
                version=row.version,
                target_plan_id=row.target_plan_id,
                needs_review=needs_review,
            )
        )
    return DiscoveryDecisionPage(
        status=status,
        total=len(relevant),
        offset=offset,
        has_more=offset + 20 < len(relevant),
        decision_snapshot_token=token,
        items=items,
    )


async def decision_evidence(
    session: AsyncSession, user_id: UUID, ledger_revision: int, group_key: str, through: date
) -> str:
    row = await DiscoveryRepository(session).decision(user_id, group_key)
    if row is None or row.status not in ("ignored", "linked"):
        raise PlanningError("discovery_not_found", 404)
    _check_normalization([row])
    page = await discover(session, user_id, ledger_revision, through, 0, None, all_groups=True)
    return "present" if any(group.key == group_key for group in page.items) else "missing"


async def change_decision(
    session: AsyncSession, user_id: UUID, payload: DiscoveryDecisionInput
) -> DiscoveryDecisionReceipt:
    await UserRepository(session).lock(user_id)
    repo = DiscoveryRepository(session)
    request_digest = digest(payload.model_dump(mode="json"))
    previous = await repo.operation(user_id, payload.operation_id)
    row = await repo.decision(user_id, payload.group_key)
    if row is not None:
        _check_normalization([row])
    if previous is not None:
        if previous.request_digest != request_digest:
            raise PlanningError("discovery_operation_conflict", 409)
        return DiscoveryDecisionReceipt.model_validate(previous.receipt)
    old_status = row.status if row else "active"
    old_version = row.version if row else 0
    transitions = {
        "ignore": ("active", "ignored"),
        "link": ("active", "linked"),
        "restore": ("ignored", "active"),
        "unlink": ("linked", "active"),
    }
    before, after = transitions[payload.action]
    if old_status != before or old_version != payload.expected_version:
        raise PlanningError("discovery_decision_conflict", 409)
    if payload.action in ("ignore", "link"):
        if (
            payload.through is None
            or payload.evidence_digest is None
            or payload.discovery_snapshot_token is None
        ):
            raise PlanningError("discovery_evidence_required", 422)
        if (
            payload.action == "link"
            and payload.target_plan_id is None
            or payload.action == "ignore"
            and payload.target_plan_id is not None
        ):
            raise PlanningError("discovery_target_invalid", 422)
        revision = await session.scalar(
            select(UserRecord.ledger_revision).where(UserRecord.id == user_id)
        )
        page = await discover(
            session,
            user_id,
            revision or 0,
            payload.through,
            0,
            payload.discovery_snapshot_token,
            all_groups=True,
        )
        group = next((item for item in page.items if item.key == payload.group_key), None)
        if (
            group is None
            or group.observation_count == 0
            or group.evidence_digest != payload.evidence_digest
        ):
            raise PlanningError("discovery_evidence_stale", 409)
        if payload.action == "link":
            assert payload.target_plan_id is not None
            plan = await PlanningRepository(session).plan(user_id, payload.target_plan_id)
            if plan is None:
                raise PlanningError("discovery_not_found", 404)
            revisions = await PlanningRepository(session).revisions(user_id)
            recent_month = max(group.observed_months)
            config = effective_config(plan, revisions, recent_month)
            if (
                config.account_id != group.account_id
                or config.currency != group.currency
                or normalize_merchant(config.merchant) != group.normalized_merchant
            ):
                raise PlanningError("discovery_duplicate_plan", 409)
        if row is None:
            row = RecurringDiscoveryDecisionRecord(
                user_id=user_id,
                group_key=group.key,
                account_id=group.account_id,
                currency=group.currency,
                normalized_merchant=group.normalized_merchant,
                merchant_normalization_version=MERCHANT_NORMALIZATION_VERSION,
                status=after,
                target_plan_id=payload.target_plan_id,
                version=1,
            )
            repo.add(row)
        else:
            row.status, row.target_plan_id, row.version = (
                after,
                payload.target_plan_id,
                old_version + 1,
            )
    else:
        if (
            payload.through is not None
            or payload.evidence_digest is not None
            or payload.discovery_snapshot_token is not None
            or payload.target_plan_id is not None
        ):
            raise PlanningError("discovery_target_invalid", 422)
        assert row is not None
        row.status, row.target_plan_id, row.version = "active", None, old_version + 1
    receipt = DiscoveryDecisionReceipt(
        operation_id=payload.operation_id,
        group_key=row.group_key,
        status=row.status,
        version=row.version,
        target_plan_id=row.target_plan_id,
        account_id=row.account_id,
        currency=row.currency,
        normalized_merchant=row.normalized_merchant,
    )
    repo.add(
        RecurringDiscoveryOperationRecord(
            user_id=user_id,
            operation_id=payload.operation_id,
            request_digest=request_digest,
            receipt=receipt.model_dump(mode="json"),
        )
    )
    return receipt
