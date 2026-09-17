"""
文件职责：提供月度报告 HTTP 接口。

主要内容：包含提交、列表、详情、状态、快照导出与删除。

关键边界：所有查询按用户隔离，导出只使用不可变快照，删除使迟到结果失效。
"""

import json
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.api.errors import ApiProblem
from bankpilot.db.models import MonthlyReportRecord, UserRecord
from bankpilot.db.report_repository import ReportConflict, ReportRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.reports import REPORT_RULE_VERSION, MonthlySnapshot, ReportStatus


def prevent_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/reports", tags=["reports"], dependencies=[Depends(prevent_cache)]
)


class CreateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: date
    idempotency_key: UUID

    @field_validator("month")
    @classmethod
    def month_start(cls, value: date) -> date:
        # 与候选扩展的前后九十天窗口保持日期可表示。
        if value.day != 1 or not 1900 <= value.year <= 9998:
            raise ValueError("Select the first day of a month between 1900 and 9998")
        return value


class ReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    month: date
    status: ReportStatus
    attempts: int
    created_at: datetime
    completed_at: datetime | None
    ledger_revision: int | None
    rule_version: str | None
    error_code: str | None
    stale: bool


class ReportDetail(ReportSummary):
    snapshot: MonthlySnapshot | None


class ReportList(BaseModel):
    items: list[ReportSummary]
    has_more: bool


def summary(record: MonthlyReportRecord, revision: int) -> ReportSummary:
    return ReportSummary(
        id=record.id,
        month=record.month,
        status=record.status,
        attempts=record.attempts,
        created_at=record.created_at,
        completed_at=record.completed_at,
        ledger_revision=record.ledger_revision,
        rule_version=record.rule_version,
        error_code=record.error_code,
        stale=record.status == ReportStatus.SUCCEEDED
        and (record.ledger_revision != revision or record.rule_version != REPORT_RULE_VERSION),
    )


async def owned_report(
    session: AsyncSession, user_id: UUID, report_id: UUID
) -> MonthlyReportRecord:
    record = await ReportRepository(session).get_for_user(user_id, report_id)
    if record is None:
        raise ApiProblem(404, "report_not_found")
    return record


async def current_revision(session: AsyncSession, user_id: UUID) -> int:
    revision = await UserRepository(session).ledger_revision(user_id)
    if revision is None:
        raise ApiProblem(404, "report_not_found")
    return revision


@router.post("", response_model=ReportSummary, status_code=202)
async def create_report(
    payload: CreateReportRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReportSummary:
    try:
        record = await ReportRepository(session).submit(
            user.id, payload.month, payload.idempotency_key
        )
        await session.commit()
    except ReportConflict as exc:
        raise ApiProblem(exc.status, exc.code) from exc
    return summary(record, await current_revision(session, user.id))


@router.get("", response_model=ReportList)
async def list_reports(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReportList:
    rows = await ReportRepository(session).list_for_user(user.id, offset=offset, limit=limit + 1)
    revision = await current_revision(session, user.id)
    return ReportList(
        items=[summary(r, revision) for r in rows[:limit]], has_more=len(rows) > limit
    )


@router.get("/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReportDetail:
    record = await owned_report(session, user.id, report_id)
    return ReportDetail(
        **summary(record, await current_revision(session, user.id)).model_dump(),
        snapshot=MonthlySnapshot.model_validate(record.snapshot) if record.snapshot else None,
    )


@router.get("/{report_id}/export")
async def export_report(
    report_id: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    record = await owned_report(session, user.id, report_id)
    if record.status != ReportStatus.SUCCEEDED or record.snapshot is None:
        raise ApiProblem(409, "report_not_ready")
    # 不夹带动态 stale 标识，重复导出同一报告得到相同内容。
    content = json.dumps(
        {"id": str(record.id), "snapshot": record.snapshot},
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    return Response(
        content,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="bankpilot-{record.month:%Y-%m}-{record.id}.json"'
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get("/{report_id}/status", response_model=ReportSummary)
async def report_status(
    report_id: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReportSummary:
    record = await ReportRepository(session).get_for_user(
        user.id, report_id, include_snapshot=False
    )
    if record is None:
        raise ApiProblem(404, "report_not_found")
    return summary(record, await current_revision(session, user.id))


@router.post("/{report_id}/delete", status_code=204)
async def delete_report(
    report_id: UUID,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    if not await ReportRepository(session).delete_for_user(user.id, report_id):
        raise ApiProblem(404, "report_not_found")
    await session.commit()
