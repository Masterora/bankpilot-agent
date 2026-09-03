"""
文件职责：编排单次 Agent 运行的持久化状态、工作流执行与异常收敛。

主要内容：
- `process`：领取 CREATED 运行，进入 PLANNING，执行工作流并写入终态。
- `_record_plan`：持久化模型决策与模型元数据，合法动作才进入 EXECUTING。
- `_fail`：将预期与非预期异常统一收敛为失败记录。
- `reconcile_interrupted`：应用启动时处理遗留非终态运行。

关键边界：模型调用和工具执行期间不持有长数据库事务；非预期错误不对外暴露内部细节。
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.adapters.local_banking import LocalBankingGateway
from bankpilot.agent.workflow import ReadOnlyBillWorkflow
from bankpilot.db.repositories import RunRepository
from bankpilot.domain.contracts import ModelPlan, RunStatus, SupportedAction
from bankpilot.errors import BankPilotError
from bankpilot.ports import ModelGateway

logger = logging.getLogger(__name__)


class RunProcessor:
    """驱动持久化运行状态，模型调用期间不长时间占用数据库事务。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        model_gateway: ModelGateway,
    ) -> None:
        self.session_factory = session_factory
        self.model_gateway = model_gateway

    async def process(self, run_id: UUID) -> None:
        """领取、执行并完成一条已创建的运行记录。"""
        # 在耗时的模型调用前先提交规划中状态，使外部能够观察实时进度。
        async with self.session_factory() as session, session.begin():
            repository = RunRepository(session)
            run = await repository.get(run_id)
            if run is None or run.status != RunStatus.CREATED.value:
                return
            user_id = run.user_id
            user_message = run.user_message
            await repository.set_status(run_id, RunStatus.PLANNING)
            await repository.add_event(run_id, "run.planning", {})

        try:
            async with self.session_factory() as session:
                workflow = ReadOnlyBillWorkflow(
                    self.model_gateway,
                    LocalBankingGateway(session),
                    after_plan=lambda plan: self._record_plan(run_id, plan),
                )
                state = await workflow.run(
                    run_id=run_id,
                    user_id=user_id,
                    user_message=user_message,
                    today=datetime.now(UTC).date(),
                )
            result = state["result"]
            async with self.session_factory() as session, session.begin():
                repository = RunRepository(session)
                await repository.add_event(
                    run_id,
                    "tool.completed",
                    {"tool": "query_transactions", "status": "SUCCEEDED"},
                )
                await repository.succeed(run_id, result.model_dump(mode="json"))
        except BankPilotError as exc:
            await self._fail(run_id, exc.code, str(exc))
        except Exception:
            # 完整诊断信息仅写入服务端日志，对外返回稳定且不含敏感信息的错误。
            logger.exception("Unexpected run processing failure", extra={"run_id": str(run_id)})
            await self._fail(run_id, "INTERNAL_ERROR", "Run processing failed")

    async def reconcile_interrupted(self) -> int:
        """在进程启动时处理遗留的非终态记录。"""
        async with self.session_factory() as session, session.begin():
            return await RunRepository(session).reconcile_interrupted()

    async def _record_plan(self, run_id: UUID, plan: ModelPlan) -> None:
        """持久化模型决策，且仅在操作允许时进入执行中状态。"""
        async with self.session_factory() as session, session.begin():
            repository = RunRepository(session)
            await repository.set_plan(
                run_id,
                draft_action=plan.decision.model_dump(mode="json"),
                model_info=plan.model_dump(mode="json", exclude={"decision"}),
            )
            if isinstance(plan.decision, SupportedAction):
                await repository.set_status(run_id, RunStatus.EXECUTING)
                await repository.add_event(run_id, "tool.started", {"tool": "query_transactions"})

    async def _fail(self, run_id: UUID, code: str, message: str) -> None:
        async with self.session_factory() as session, session.begin():
            await RunRepository(session).fail(run_id, code=code, message=message)
