"""
文件职责：封装规则核查判断的持久化。
主要内容：按用户和证据键读取、锁定及保存判断。
关键边界：不校验业务证据、不提交事务；调用方先锁用户并重新确认事实。
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import ReviewDecisionRecord
from bankpilot.domain.contracts import BillAnomaly, ReviewState


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def decisions(self, user_id: UUID, keys: list[str]) -> dict[str, ReviewDecisionRecord]:
        records = await self.session.scalars(
            select(ReviewDecisionRecord).where(
                ReviewDecisionRecord.user_id == user_id, ReviewDecisionRecord.key.in_(keys)
            )
        )
        return {record.key: record for record in records}

    async def save(
        self, user_id: UUID, key: str, state: ReviewState, note: str, evidence: BillAnomaly
    ) -> None:
        record = await self.session.get(ReviewDecisionRecord, (user_id, key), with_for_update=True)
        if record is None:
            record = ReviewDecisionRecord(user_id=user_id, key=key)
            self.session.add(record)
        record.state, record.note = state, note.strip()
        record.evidence = evidence.model_dump(mode="json")
