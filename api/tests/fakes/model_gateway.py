"""
文件职责：提供可预测的模型网关测试替身。
主要内容：`FakeModelGateway` 将转账语句判定为不支持，其他输入转为本月账单查询。
关键边界：输出固定且不访问网络，仅用于测试。
"""

from datetime import date
from uuid import UUID

from bankpilot.domain.contracts import (
    ModelPlan,
    ModelUsage,
    SupportedAction,
    TransactionQuery,
    UnsupportedIntent,
)


class FakeModelGateway:
    async def plan(self, user_message: str, *, today: date, run_id: UUID) -> ModelPlan:
        if "转账" in user_message:
            decision = UnsupportedIntent(
                kind="unsupported",
                user_message="当前版本仅支持账单查询。",
            )
        else:
            decision = SupportedAction(
                kind="action",
                tool="query_transactions",
                arguments=TransactionQuery(
                    start_date=today.replace(day=1),
                    end_date=today,
                ),
                user_message="正在查询本月账单。",
            )
        return ModelPlan(
            decision=decision,
            provider="test",
            model="fixed-test-model",
            request_id=str(run_id),
            latency_ms=1,
            usage=ModelUsage(total_tokens=10),
        )
