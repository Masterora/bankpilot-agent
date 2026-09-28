"""分类修正及其账本派生状态在同一事务内更新。"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import TransactionRecord
from bankpilot.db.transaction_repository import TransactionRepository
from bankpilot.services.attention import synchronize_ledger


async def correct_category(
    session: AsyncSession,
    *,
    user_id: UUID,
    transaction_id: UUID,
    category: str,
    expected_revision: int,
) -> TransactionRecord | None:
    record = await TransactionRepository(session).set_category_override(
        user_id=user_id,
        transaction_id=transaction_id,
        category=category,
        expected_revision=expected_revision,
    )
    if record is not None:
        await synchronize_ledger(session, user_id, {transaction_id})
    return record
