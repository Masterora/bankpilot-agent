"""
文件职责：编排确定性规则核查和搜索结果证据投影。
主要内容：构造规则证据键、合并用户判断、投影搜索匹配项并在保存前重查事实。
关键边界：写入先锁用户，防止验证与撤销交错；投影校验查询版本，事务由调用方提交。
"""
import hashlib
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.adapters.local_banking import LocalBankingGateway
from bankpilot.db.review_repository import ReviewRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.bill_analysis import analyze_bill
from bankpilot.domain.contracts import (
    BillAnalysis,
    BillAnomaly,
    ReviewItem,
    ReviewList,
    ReviewState,
)
from bankpilot.domain.transaction_search import (
    SEARCH_VERSION,
    ProjectedReview,
    ReviewProjection,
    ReviewProjectionRequest,
    SearchFilters,
)
from bankpilot.errors import PlanningError
from bankpilot.services.transaction_search import check_version, matching_items


def evidence_key(anomaly: BillAnomaly) -> str:
    """同规则与交易集合共用判断，查询顺序不改变身份。"""
    value = anomaly.rule_id + ":" + ",".join(sorted(str(i) for i in anomaly.transaction_ids))
    return hashlib.sha256(value.encode()).hexdigest()


class ReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ReviewRepository(session)

    async def analysis(self, user_id: UUID, start: date, end: date) -> BillAnalysis:
        transactions = await LocalBankingGateway(self.session).query_transactions(
            user_id=user_id, start_date=start, end_date=end
        )
        return analyze_bill(transactions.items)

    async def read(self, user_id: UUID, start: date, end: date) -> ReviewList:
        analysis = await self.analysis(user_id, start, end)
        keyed = [(evidence_key(item), item) for item in analysis.anomalies]
        decisions = await self.repository.decisions(user_id, [key for key, _ in keyed])
        return ReviewList(
            summaries=analysis.currency_summaries,
            items=[
                ReviewItem.model_validate(
                    {
                        **anomaly.model_dump(),
                        "key": key,
                        "state": decisions[key].state if key in decisions else "pending",
                        "note": decisions[key].note if key in decisions else "",
                    }
                )
                for key, anomaly in keyed
            ],
        )

    async def save(
        self,
        user_id: UUID,
        start: date,
        end: date,
        key: str,
        state: ReviewState,
        note: str,
        expected_revision: int,
    ) -> bool:
        await UserRepository(self.session).lock(user_id)
        await check_version(self.session, user_id, expected_revision, SEARCH_VERSION)
        analysis = await self.analysis(user_id, start, end)
        anomaly = next((a for a in analysis.anomalies if evidence_key(a) == key), None)
        if anomaly is None:
            return False
        await self.repository.save(user_id, key, state, note, anomaly)
        return True


async def project_reviews(
    session: AsyncSession, uid: UUID, request: ReviewProjectionRequest
) -> ReviewProjection:
    await check_version(session, uid, request.expected_revision, SEARCH_VERSION)
    # Compute rules against the complete original period, never against a filtered page.
    items = await matching_items(
        session,
        uid,
        SearchFilters(
            start_date=request.start_date,
            end_date=request.end_date,
        ),
    )
    analysis = analyze_bill(list(items))
    selected = set(request.transaction_ids)
    keyed = [
        (evidence_key(a), a) for a in analysis.anomalies if selected.intersection(a.transaction_ids)
    ]
    keyed.sort(key=lambda pair: pair[0])
    decisions = await ReviewRepository(session).decisions(uid, [key for key, _ in keyed])
    by_id = {item.id: item for item in items}
    visible = (
        [pair for pair in keyed if pair[0] == request.evidence_key]
        if request.evidence_key
        else keyed[request.offset : request.offset + 20]
    )
    if request.evidence_key and not visible:
        raise PlanningError("evidence_unavailable", 404)
    result = []
    for key, anomaly in visible:
        evidence = [by_id[identity] for identity in anomaly.transaction_ids]
        result.append(
            ProjectedReview(
                review=ReviewItem(
                    **anomaly.model_dump(),
                    key=key,
                    state=decisions[key].state if key in decisions else "pending",
                    note=decisions[key].note if key in decisions else "",
                ),
                evidence=evidence[request.evidence_offset : request.evidence_offset + 20],
                evidence_total=len(evidence),
                evidence_offset=request.evidence_offset,
            )
        )
    return ReviewProjection(
        items=result,
        total_count=len(keyed),
        offset=request.offset,
        ledger_revision=request.expected_revision,
    )
