"""
文件职责：提供确定性异常核查与运行历史入口。
主要内容：重新计算规则证据、保存正常或待核实判断、恢复待处理、读取用户历史。
关键边界：结论按用户和规则证据隔离；服务端重算证据，不接受客户端伪造异常或修改金额。
"""

import hashlib
from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.adapters.local_banking import LocalBankingGateway
from bankpilot.api.dependencies import get_current_user, get_db_session
from bankpilot.db.models import ReviewDecisionRecord, RunRecord, UserRecord
from bankpilot.domain.bill_analysis import analyze_bill
from bankpilot.domain.contracts import BillAnalysis, BillAnomaly, TransactionQuery

router = APIRouter(prefix="/api/v1", tags=["reviews"])


def evidence_key(anomaly: BillAnomaly) -> str:
    """相同规则与交易集合共用结论，改变查询顺序不会产生重复待办。"""
    value = anomaly.rule_id + ":" + ",".join(sorted(str(i) for i in anomaly.transaction_ids))
    return hashlib.sha256(value.encode()).hexdigest()


class ReviewRequest(TransactionQuery):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: Literal["pending", "normal", "follow_up"]
    note: str = Field(default="", max_length=500)


async def current_analysis(
    session: AsyncSession, user_id: UUID, start: date, end: date
) -> BillAnalysis:
    """限制查询期间后读取用户数据；异常规则无需模型参与。"""
    if end < start or (end - start).days > 366:
        raise HTTPException(422, "Select an ordered period of at most 366 days")
    transactions = await LocalBankingGateway(session).query_transactions(
        user_id=user_id, start_date=start, end_date=end
    )
    return analyze_bill(transactions.items)


@router.get("/reviews")
async def reviews(
    start_date: date,
    end_date: date,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """返回当前规则候选和已保存判断；不将判断解释为已退款或银行已处理。"""
    analysis = await current_analysis(session, user.id, start_date, end_date)
    keys = [evidence_key(a) for a in analysis.anomalies]
    records = await session.scalars(
        select(ReviewDecisionRecord).where(
            ReviewDecisionRecord.user_id == user.id, ReviewDecisionRecord.key.in_(keys)
        )
    )
    decisions = {r.key: r for r in records}
    return {
        "summaries": analysis.currency_summaries,
        "items": [
            {
                **a.model_dump(mode="json"),
                "key": evidence_key(a),
                "state": decisions[evidence_key(a)].state
                if evidence_key(a) in decisions
                else "pending",
                "note": decisions[evidence_key(a)].note if evidence_key(a) in decisions else "",
            }
            for a in analysis.anomalies
        ],
    }


@router.post("/reviews", status_code=204)
async def save_review(
    payload: ReviewRequest,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """写入前重算当前证据；被撤销的交易不能继续提交判断。"""
    analysis = await current_analysis(session, user.id, payload.start_date, payload.end_date)
    anomaly = next((a for a in analysis.anomalies if evidence_key(a) == payload.key), None)
    if anomaly is None:
        raise HTTPException(404, "Review evidence is no longer available")
    record = await session.get(ReviewDecisionRecord, (user.id, payload.key), with_for_update=True)
    if record is None:
        record = ReviewDecisionRecord(user_id=user.id, key=payload.key)
        session.add(record)
    record.state, record.note = payload.state, payload.note.strip()
    record.evidence = anomaly.model_dump(mode="json")
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Review changed concurrently; reload and retry") from exc


@router.get("/run-history")
async def run_history(
    user: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> dict[str, Any]:
    """仅列出当前用户最近五十次运行，不读取其他用户的任务或结果。"""
    rows = await session.scalars(
        select(RunRecord)
        .where(RunRecord.user_id == user.id)
        .order_by(RunRecord.created_at.desc(), RunRecord.id.desc())
        .limit(50)
    )
    return {
        "items": [
            {
                "id": row.id,
                "message": row.user_message,
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }
