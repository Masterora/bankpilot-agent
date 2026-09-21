"""
文件职责：定义工作流与助手依赖的抽象能力端口。
主要内容：ModelGateway 规划、AssistantGateway 工具决策、BankingGateway 账本读取，
以及 ReviewGateway 一致快照核查。
关键边界：核心流程依赖 Protocol，不直接依赖模型供应商或具体数据库实现。
"""
from datetime import date
from typing import Protocol
from uuid import UUID

from bankpilot.domain.assistant import Decision
from bankpilot.domain.contracts import ModelPlan, ReviewSnapshot, TransactionResult


class ModelGateway(Protocol):
    async def plan(self, user_message: str, *, today: date, run_id: UUID) -> ModelPlan: ...


class BankingGateway(Protocol):
    async def query_transactions(
        self, *, user_id: UUID, start_date: date, end_date: date
    ) -> TransactionResult: ...


class ReviewGateway(Protocol):
    """原子读取交易与核查证据，隔离 Agent 对账本存储和关系规则的依赖。"""

    async def review_transactions(
        self, *, user_id: UUID, start_date: date, end_date: date
    ) -> ReviewSnapshot: ...


class AssistantGateway(Protocol):
    async def decide(self, messages: list[dict[str, str]]) -> "Decision": ...
