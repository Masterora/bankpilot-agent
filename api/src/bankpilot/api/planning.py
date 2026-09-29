"""
文件职责：提供月度预算与手动周期扣款的 HTTP 接口。
主要内容：预算读取、保存、复制、删除，以及周期配置、未来修订、逐期匹配和未发生确认。
关键边界：读取使用一致快照，写入经过服务端校验后显式提交，不触发真实扣款。
"""

from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import (
    get_app_settings,
    get_current_user,
    get_db_session,
    get_snapshot_session,
    get_snapshot_user,
)
from bankpilot.api.errors import ApiProblem
from bankpilot.config import Settings
from bankpilot.db.models import UserRecord
from bankpilot.domain.contracts import TransactionCategory
from bankpilot.domain.planning import (
    BudgetCopyResult,
    BudgetInput,
    BudgetWorkspace,
    Currency,
    PlanningInput,
    RecurringCancelRevisionInput,
    RecurringEditInput,
    RecurringInput,
    RecurringMatchInput,
    RecurringSkipInput,
    RecurringStatusInput,
    RecurringTransaction,
    RecurringWorkspace,
)
from bankpilot.domain.recurring_discovery import (
    DiscoveryDecisionInput,
    DiscoveryDecisionPage,
    DiscoveryDecisionReceipt,
    DiscoveryPage,
    DiscoveryProposal,
    DiscoveryProposalInput,
    month_index,
    month_start,
)
from bankpilot.services import budgets as budget_service
from bankpilot.services import recurring as recurring_service
from bankpilot.services import recurring_discovery as discovery_service
from bankpilot.services.planning_reads import budget_workspace, recurring_workspace

router = APIRouter(prefix="/api/v1", tags=["planning"])


def checked_month(value: date) -> date:
    if not 1900 <= value.year <= 9998:
        raise ApiProblem(422, "invalid_month", "Month out of range")
    return value.replace(day=1)


class MonthInput(PlanningInput):
    month: date


class RemoveBudgetInput(MonthInput):
    budget_id: UUID
    category: TransactionCategory
    currency: Currency
    expected_version: int = Field(ge=1)


class DiscoveryAvailability(BaseModel):
    enabled: bool


class DiscoveryEvidenceStatus(BaseModel):
    evidence_status: str


def discovery_through(value: date | None) -> date:
    current = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    latest = month_start(month_index(current) - 1)
    target = value or latest
    if target.day != 1 or not 1900 <= target.year <= 9998 or target > latest:
        raise ApiProblem(422, "invalid_month", "A completed month is required")
    return target


def discovery_enabled(settings: Settings) -> None:
    if not settings.recurring_discovery_enabled:
        raise ApiProblem(404, "discovery_unavailable")


@router.get("/budgets", response_model=BudgetWorkspace)
async def budgets(
    month: date,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> BudgetWorkspace:
    return await budget_workspace(session, user.id, checked_month(month))


@router.post("/budgets", status_code=204)
async def save_budget(
    payload: BudgetInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    checked_month(payload.month)
    await budget_service.save_budget(session, user.id, payload)
    await session.commit()


@router.post("/budgets/copy")
async def copy_budgets(
    payload: MonthInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> BudgetCopyResult:
    copied = await budget_service.copy_budgets(session, user.id, checked_month(payload.month))
    await session.commit()
    return copied


@router.post("/budgets/delete", status_code=204)
async def remove_budget(
    payload: RemoveBudgetInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await budget_service.remove_budget(
        session,
        user.id,
        checked_month(payload.month),
        payload.category,
        payload.currency,
        payload.expected_version,
        payload.budget_id,
    )
    await session.commit()


@router.get("/recurring", response_model=RecurringWorkspace)
async def recurring(
    month: date,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> RecurringWorkspace:
    return await recurring_workspace(session, user.id, checked_month(month))


@router.get("/recurring/candidates", response_model=list[RecurringTransaction])
async def recurring_candidates(
    month: date,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> list[RecurringTransaction]:
    return await recurring_service.recurring_candidates(session, user.id, checked_month(month))


@router.get("/recurring/discovery", response_model=DiscoveryPage)
async def recurring_discovery(
    through: date | None = None,
    offset: int = 0,
    discovery_snapshot_token: str | None = None,
    settings: Settings = Depends(get_app_settings),
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> DiscoveryPage:
    discovery_enabled(settings)
    target = discovery_through(through)
    if offset < 0 or offset % 20:
        raise ApiProblem(422, "invalid_offset", "Offset must be a nonnegative page boundary")
    if offset and discovery_snapshot_token is None:
        raise ApiProblem(422, "discovery_snapshot_required")
    return await discovery_service.discover(
        session, user.id, user.ledger_revision, target, offset, discovery_snapshot_token
    )


@router.get("/recurring/discovery/decisions", response_model=DiscoveryDecisionPage)
async def recurring_discovery_decisions(
    status: str,
    offset: int = 0,
    decision_snapshot_token: str | None = None,
    settings: Settings = Depends(get_app_settings),
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> DiscoveryDecisionPage:
    discovery_enabled(settings)
    if status not in ("ignored", "linked") or offset < 0 or offset % 20:
        raise ApiProblem(422, "discovery_decisions_invalid")
    if offset and decision_snapshot_token is None:
        raise ApiProblem(422, "discovery_snapshot_required")
    return await discovery_service.saved_decisions(
        session, user.id, status, offset, decision_snapshot_token
    )


@router.get(
    "/recurring/discovery/decisions/{group_key}/evidence", response_model=DiscoveryEvidenceStatus
)
async def recurring_discovery_decision_evidence(
    group_key: str,
    through: date | None = None,
    settings: Settings = Depends(get_app_settings),
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> DiscoveryEvidenceStatus:
    discovery_enabled(settings)
    status = await discovery_service.decision_evidence(
        session, user.id, user.ledger_revision, group_key, discovery_through(through)
    )
    return DiscoveryEvidenceStatus(evidence_status=status)


@router.post("/recurring/discovery/decisions", response_model=DiscoveryDecisionReceipt)
async def recurring_discovery_decision(
    payload: DiscoveryDecisionInput,
    settings: Settings = Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DiscoveryDecisionReceipt:
    discovery_enabled(settings)
    if payload.action in ("ignore", "link"):
        discovery_through(payload.through)
    receipt = await discovery_service.change_decision(session, user.id, payload)
    await session.commit()
    return receipt


@router.get("/recurring/discovery/availability", response_model=DiscoveryAvailability)
async def recurring_discovery_availability(
    settings: Settings = Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
) -> DiscoveryAvailability:
    return DiscoveryAvailability(enabled=settings.recurring_discovery_enabled)


@router.post("/recurring/discovery/proposals", response_model=DiscoveryProposal)
async def recurring_discovery_proposal(
    payload: DiscoveryProposalInput,
    settings: Settings = Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DiscoveryProposal:
    discovery_enabled(settings)
    discovery_through(payload.through)
    result = await discovery_service.create_proposal(session, user.id, payload)
    await session.commit()
    return result


@router.get("/recurring/discovery/proposals/{proposal_id}", response_model=DiscoveryProposal)
async def recurring_discovery_proposal_detail(
    proposal_id: UUID,
    settings: Settings = Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DiscoveryProposal:
    discovery_enabled(settings)
    return await discovery_service.get_proposal(session, user.id, proposal_id)


@router.post(
    "/recurring/discovery/proposals/{proposal_id}/confirm", response_model=DiscoveryProposal
)
async def recurring_discovery_proposal_confirm(
    proposal_id: UUID,
    settings: Settings = Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DiscoveryProposal:
    discovery_enabled(settings)
    result = await discovery_service.confirm_proposal(session, user.id, proposal_id)
    await session.commit()
    return result


@router.post("/recurring", status_code=204)
async def create_recurring(
    payload: RecurringInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await recurring_service.create_recurring(session, user.id, payload)
    await session.commit()


@router.post("/recurring/{identity}/status", status_code=204)
async def recurring_status(
    identity: UUID,
    payload: RecurringStatusInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await recurring_service.set_recurring_status(session, user.id, identity, payload)
    await session.commit()


@router.post("/recurring/{identity}/match", status_code=204)
async def recurring_match(
    identity: UUID,
    payload: RecurringMatchInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await recurring_service.match_recurring(session, user.id, identity, payload)
    await session.commit()


@router.post("/recurring/{identity}/edit", status_code=204)
async def edit_recurring(
    identity: UUID,
    payload: RecurringEditInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await recurring_service.edit_recurring(session, user.id, identity, payload)
    await session.commit()


@router.get("/recurring/draft", response_model=RecurringInput)
async def recurring_draft(
    transaction_id: UUID,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> RecurringInput:
    return await recurring_service.recurring_draft(session, user.id, transaction_id)


@router.post("/recurring/{identity}/skip", status_code=204)
async def skip_recurring(
    identity: UUID,
    payload: RecurringSkipInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await recurring_service.skip_recurring(session, user.id, identity, payload)
    await session.commit()


@router.post("/recurring/{identity}/cancel-revision", status_code=204)
async def cancel_revision(
    identity: UUID,
    payload: RecurringCancelRevisionInput,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await recurring_service.cancel_revision(session, user.id, identity, payload)
    await session.commit()
