"""
文件职责：定义核心流程依赖的抽象端口。

主要内容：
- `ModelGateway`：将用户语言转换为模型计划。
- `BankingGateway`：按用户和日期范围查询交易。

关键边界：业务工作流只依赖这些 `Protocol`，不直接依赖供应商或数据库实现。
"""

from datetime import date
from typing import Protocol
from uuid import UUID

from bankpilot.domain.contracts import ModelPlan, TransactionResult


class ModelGateway(Protocol):
    async def plan(self, user_message: str, *, today: date, run_id: UUID) -> ModelPlan: ...


class BankingGateway(Protocol):
    async def query_transactions(
        self, *, user_id: UUID, start_date: date, end_date: date
    ) -> TransactionResult: ...
