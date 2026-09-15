"""
文件职责：编排确定性规则核查。
主要内容：计算规则证据、组合已保存判断、保存前重新验证事实。
关键边界：写入先锁用户，防止证据检查与撤销交错；事务由调用方提交。
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
        self, user_id: UUID, start: date, end: date, key: str, state: ReviewState, note: str
    ) -> bool:
        await UserRepository(self.session).lock(user_id)
        analysis = await self.analysis(user_id, start, end)
        anomaly = next((a for a in analysis.anomalies if evidence_key(a) == key), None)
        if anomaly is None:
            return False
        await self.repository.save(user_id, key, state, note, anomaly)
        return True
