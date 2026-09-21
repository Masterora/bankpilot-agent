"""
文件职责：提供月度预算与手动周期扣款的 HTTP 接口。
主要内容：预算读取、保存、复制、删除，以及周期配置、未来修订、逐期匹配和未发生确认。
关键边界：读取使用一致快照，写入经过服务端校验后显式提交，不触发真实扣款。
"""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import (
    get_current_user,
    get_db_session,
    get_snapshot_session,
    get_snapshot_user,
)
from bankpilot.api.errors import ApiProblem
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
from bankpilot.services import budgets as budget_service
from bankpilot.services import recurring as recurring_service

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


@router.get("/budgets", response_model=BudgetWorkspace)
async def budgets(
    month: date,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> BudgetWorkspace:
    return await budget_service.budget_workspace(session, user.id, checked_month(month))


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
    return await recurring_service.recurring_workspace(session, user.id, checked_month(month))


@router.get("/recurring/candidates", response_model=list[RecurringTransaction])
async def recurring_candidates(
    month: date,
    user: UserRecord = Depends(get_snapshot_user),
    session: AsyncSession = Depends(get_snapshot_session),
) -> list[RecurringTransaction]:
    return await recurring_service.recurring_candidates(session, user.id, checked_month(month))


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
