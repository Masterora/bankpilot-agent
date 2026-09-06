"""
文件职责：统一预览与导入的账户归属解析。
主要内容：按稳定 UUID 绑定账户，校验来源和币种；新账户按名称查重。
关键边界：名称仅用于展示及新建查重；显式绑定不能跨用户、跨来源或跨币种。
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import AccountRecord


async def resolve_account(
    session: AsyncSession,
    *,
    user_id: UUID,
    account_id: UUID | None,
    name: str,
    currency: str,
    source: str,
) -> AccountRecord | None:
    """显式选择优先按 ID 解析；不允许失效 ID 降级为创建同名账户。"""
    # 解析器版本只属于批次证据，不能成为账户身份的一部分。
    source = source.partition(":")[0]
    condition = AccountRecord.id == account_id if account_id else AccountRecord.name == name
    account = await session.scalar(
        select(AccountRecord).where(
            AccountRecord.user_id == user_id,
            condition,
            *([] if account_id else [AccountRecord.currency == currency]),
        )
    )
    if account_id and account is None:
        raise ValueError("Account is unavailable; select an account again")
    if account and (account.currency != currency or account.source != source):
        raise ValueError("Account source or currency does not match the statement")
    return account
