"""
文件职责：验证交易查询领域契约的日期限制。
主要内容：覆盖起止日期倒置与超过一年的查询范围。
关键边界：无效范围必须在进入工作流和数据库前被 Pydantic 拒绝。
"""

from datetime import date

import pytest
from pydantic import ValidationError

from bankpilot.domain.contracts import TransactionQuery


def test_transaction_query_rejects_inverted_period() -> None:
    with pytest.raises(ValidationError):
        TransactionQuery(start_date=date(2026, 9, 2), end_date=date(2026, 9, 1))


def test_transaction_query_rejects_ranges_over_one_year() -> None:
    with pytest.raises(ValidationError):
        TransactionQuery(start_date=date(2025, 1, 1), end_date=date(2026, 9, 1))
