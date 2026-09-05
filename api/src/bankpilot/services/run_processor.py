"""
文件职责：编排单次 Agent 运行的持久化状态、工作流执行与异常收敛。

主要内容：
- `process`：领取 CREATED 运行，执行查询与确定性分析并写入终态。
- `_record_plan`：持久化模型决策与模型元数据，合法动作才进入 EXECUTING。
- `_fail`：将预期与非预期异常统一收敛为失败记录。
- `reconcile_interrupted`：应用启动时处理遗留非终态运行。

关键边界：模型调用和工具执行期间不持有长数据库事务；非预期错误不对外暴露内部细节。
"""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.adapters.local_banking import LocalBankingGateway
from bankpilot.agent.workflow import ReadOnlyBillWorkflow
from bankpilot.db.models import RunRecord
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

        heartbeat = asyncio.create_task(self._heartbeat(run_id))
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
                current = await repository.get(run_id)
                if current is None or current.status != RunStatus.EXECUTING.value:
                    return
                await repository.add_event(
                    run_id,
                    "tool.completed",
                    {"tool": "query_transactions", "status": "SUCCEEDED"},
                )
                await repository.add_event(
                    run_id,
                    "analysis.completed",
                    {
                        "anomaly_count": len(result.analysis.anomalies),
                        "category_count": len(result.analysis.category_summaries),
                    },
                )
                await repository.succeed(run_id, result.model_dump(mode="json"))
        except BankPilotError as exc:
            await self._fail(run_id, exc.code, str(exc))
        except Exception:
            # 完整诊断信息仅写入服务端日志，对外返回稳定且不含敏感信息的错误。
            logger.exception("Unexpected run processing failure", extra={"run_id": str(run_id)})
            await self._fail(run_id, "INTERNAL_ERROR", "Run processing failed")
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat(self, run_id: UUID) -> None:
        """每十五秒续约；失去数据库连接时停止续约，由超时扫描收敛状态。"""
        try:
            while True:
                await asyncio.sleep(15)
                async with self.session_factory() as session, session.begin():
                    await session.execute(
                        update(RunRecord)
                        .where(
                            RunRecord.id == run_id,
                            RunRecord.status.in_(
                                [RunStatus.PLANNING.value, RunStatus.EXECUTING.value]
                            ),
                        )
                        .values(updated_at=datetime.now(UTC))
                    )
        except Exception:
            logger.exception("Run heartbeat failed", extra={"run_id": str(run_id)})

    async def recover_expired(self) -> None:
        """周期扫描失联任务，无需等待服务重启，不重新执行模型或工具。"""
        while True:
            await asyncio.sleep(15)
            try:
                await self.reconcile_interrupted()
            except Exception:
                logger.exception("Expired run recovery failed")

    async def reconcile_interrupted(self) -> int:
        """在进程启动时处理遗留的非终态记录。"""
        async with self.session_factory() as session, session.begin():
            return await RunRepository(session).reconcile_interrupted()

    async def _record_plan(self, run_id: UUID, plan: ModelPlan) -> None:
        """持久化模型决策，且仅在操作允许时进入执行中状态。"""
        async with self.session_factory() as session, session.begin():
            repository = RunRepository(session)
            run = await repository.get(run_id)
            if run is None or run.status != RunStatus.PLANNING.value:
                raise BankPilotError("Run is no longer active")
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
            repository = RunRepository(session)
            run = await repository.get(run_id)
            if run is not None and run.status in {
                RunStatus.PLANNING.value,
                RunStatus.EXECUTING.value,
            }:
                await repository.fail(run_id, code=code, message=message)
