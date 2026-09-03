"""
文件职责：定义账单查询 Agent 的 LangGraph 状态与节点流程。

主要内容：
- `AgentState`：携带运行 ID、用户 ID、模型计划、交易和最终结果。
- `ReadOnlyBillWorkflow`：按 plan、execute、respond/reject 节点组装工作流。
- `after_plan`：允许应用层在执行前持久化模型计划。

关键边界：只有 `query_transactions` 能进入执行节点，不支持的意图直接终止。
"""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import NotRequired, TypedDict, cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from bankpilot.domain.contracts import ModelPlan, RunResult, SupportedAction, TransactionResult
from bankpilot.errors import ActionNotAllowedError
from bankpilot.ports import BankingGateway, ModelGateway


class AgentState(TypedDict):
    """在工作流规划与执行节点之间传递的强类型状态。"""

    run_id: UUID
    user_id: UUID
    user_message: str
    today: date
    plan: NotRequired[ModelPlan]
    transactions: NotRequired[TransactionResult]
    result: NotRequired[RunResult]


class ReadOnlyBillWorkflow:
    """通过显式操作白名单执行 v0.1 的唯一能力。"""

    def __init__(
        self,
        model_gateway: ModelGateway,
        banking_gateway: BankingGateway,
        after_plan: Callable[[ModelPlan], Awaitable[None]] | None = None,
    ) -> None:
        self.model_gateway = model_gateway
        self.banking_gateway = banking_gateway
        self.after_plan = after_plan
        # 所有副作用只能发生在执行节点，任何拒绝都必须立即终止流程。
        graph = StateGraph(AgentState)
        graph.add_node("plan", self._plan)
        graph.add_node("execute", self._execute)
        graph.add_node("respond", self._respond)
        graph.add_node("reject", self._reject)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan",
            self._route_after_plan,
            {"execute": "execute", "reject": "reject"},
        )
        graph.add_edge("execute", "respond")
        graph.add_edge("respond", END)
        graph.add_edge("reject", END)
        self.graph = graph.compile()

    async def run(
        self, *, run_id: UUID, user_id: UUID, user_message: str, today: date
    ) -> AgentState:
        """执行一次隔离请求，并在状态中携带已认证的用户 ID。"""
        initial: AgentState = {
            "run_id": run_id,
            "user_id": user_id,
            "user_message": user_message,
            "today": today,
        }
        return cast(AgentState, await self.graph.ainvoke(initial))

    async def _plan(self, state: AgentState) -> dict[str, ModelPlan]:
        plan = await self.model_gateway.plan(
            state["user_message"], today=state["today"], run_id=state["run_id"]
        )
        if self.after_plan is not None:
            await self.after_plan(plan)
        return {"plan": plan}

    @staticmethod
    def _route_after_plan(state: AgentState) -> str:
        return "execute" if isinstance(state["plan"].decision, SupportedAction) else "reject"

    async def _execute(self, state: AgentState) -> dict[str, TransactionResult]:
        """在访问银行数据前再次强制检查工具白名单。"""
        decision = state["plan"].decision
        if not isinstance(decision, SupportedAction) or decision.tool != "query_transactions":
            raise ActionNotAllowedError("Only query_transactions is allowed in v0.1")
        transactions = await self.banking_gateway.query_transactions(
            user_id=state["user_id"],
            start_date=decision.arguments.start_date,
            end_date=decision.arguments.end_date,
        )
        return {"transactions": transactions}

    @staticmethod
    async def _respond(state: AgentState) -> dict[str, RunResult]:
        transactions = state["transactions"]
        count = len(transactions.items)
        message = (
            f"已查询 {transactions.start_date.isoformat()} 至 "
            f"{transactions.end_date.isoformat()} 的账单，共 {count} 笔。"
        )
        return {"result": RunResult(message=message, transactions=transactions)}

    @staticmethod
    async def _reject(state: AgentState) -> dict[str, RunResult]:
        decision = state["plan"].decision
        raise ActionNotAllowedError(decision.user_message)
