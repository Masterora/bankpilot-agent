"""
文件职责：实现基于本地数据库的只读银行网关与确定性分类装配。

主要内容：
- `LocalBankingGateway`：实现 `BankingGateway` 所需的交易查询能力。
- 持久化转换：将交易、账户和用户分类修正组装为领域结果。

关键边界：用户归属和日期过滤由仓储层强制执行，本适配器不提供写操作。
"""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import TransactionRecord
from bankpilot.db.repositories import TransactionRepository
from bankpilot.domain.bill_analysis import classify_transaction
from bankpilot.domain.contracts import TransactionCategory, TransactionItem, TransactionResult


class LocalBankingGateway:
    """将持久化记录转换为与供应商无关的领域契约。"""

    def __init__(self, session: AsyncSession) -> None:
        self.repository = TransactionRepository(session)

    async def query_transactions(
        self, *, user_id: UUID, start_date: date, end_date: date
    ) -> TransactionResult:
        """仅查询已认证用户名下账户在指定时间段内的交易。"""
        rows = await self.repository.query_for_user(
            user_id=user_id, start_date=start_date, end_date=end_date
        )
        return TransactionResult(
            start_date=start_date,
            end_date=end_date,
            items=[
                self._to_item(transaction, account_name, override)
                for transaction, account_name, override in rows
            ],
        )

    @staticmethod
    def _to_item(
        transaction: TransactionRecord, account_name: str, override: str | None
    ) -> TransactionItem:
        """把持久化记录转换成带有可解释分类的领域交易。"""
        classification = classify_transaction(
            merchant=transaction.merchant,
            description=transaction.description,
            amount=transaction.amount,
            override=TransactionCategory(override) if override is not None else None,
        )
        return TransactionItem(
            id=transaction.id,
            occurred_at=transaction.occurred_at,
            merchant=transaction.merchant,
            description=transaction.description,
            amount=transaction.amount,
            currency=transaction.currency,
            account_name=account_name,
            category=classification.category,
            category_source=classification.source,
            category_rule_id=classification.rule_id,
        )
