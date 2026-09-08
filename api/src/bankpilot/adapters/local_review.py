"""
文件职责：实现 Agent 的只读账单核查快照端口。

主要内容：在可重复读事务内组合期间流水、关系调整、双方证据和覆盖限制。
关键边界：只返回当前用户数据；模型不接触流水；读取失败不得降级为无调整成功。
事务必须由本适配器创建，确保全部查询使用相同数据库快照。
"""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.adapters.local_banking import LocalBankingGateway
from bankpilot.domain.contracts import BillReview, ReviewCoverage, ReviewSnapshot
from bankpilot.errors import ToolExecutionError
from bankpilot.services.transaction_relations import RelationError, relation_workspace


class LocalReviewGateway:
    """封装快照事务生命周期，不依赖模型调用期间使用的数据库连接。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def review_transactions(
        self, *, user_id: UUID, start_date: date, end_date: date
    ) -> ReviewSnapshot:
        """先限定工作区，再读取流水；可重复读防止并发导入或分类更正撕裂结果。"""
        try:
            async with self.session_factory() as session:
                await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                snapshot_at = datetime.now(UTC)
                workspace = await relation_workspace(
                    session, user_id, start_date, end_date, acquire_lock=False
                )
                transactions = await LocalBankingGateway(session).query_transactions(
                    user_id=user_id, start_date=start_date, end_date=end_date
                )
                evidence_ids = {t.id for t in transactions.items} | {
                    item[key]
                    for item in workspace["items"]
                    for key in ("first_id", "second_id")
                }
                return ReviewSnapshot(
                    transactions=transactions,
                    review=BillReview(
                        snapshot_at=snapshot_at,
                        adjusted_summaries=workspace["summaries"],
                        relations=workspace["items"],
                        evidence=[
                            row for row in workspace["transactions"] if row["id"] in evidence_ids
                        ],
                        candidates_truncated=workspace["truncated"],
                        coverage=ReviewCoverage(
                            start_date=start_date,
                            end_date=end_date,
                            transaction_count=len(transactions.items),
                            import_batch_count=len(
                                {t.import_batch_id for t in transactions.items if t.import_batch_id}
                            ),
                        ),
                    ),
                )
        except RelationError as exc:
            if exc.code == "narrow_period":
                raise ToolExecutionError("交易过多，请缩小查询日期范围。") from exc
            raise ToolExecutionError("账单核查证据读取失败，请重试。") from exc
        except (SQLAlchemyError, OSError) as exc:
            raise ToolExecutionError("账单数据暂时不可用，请稍后重试。") from exc
