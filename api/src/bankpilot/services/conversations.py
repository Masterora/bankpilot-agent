"""
文件职责：管理持久助手会话和可恢复轮次生命周期。
主要内容：轮次幂等提交、受理上下文快照、过期恢复、历史读取及迟到结果和提案写回隔离。
关键边界：通过短事务与版本约束写回；等待模型不占用数据库事务，删除或过期后不得复活旧结果。
"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bankpilot.config import Settings
from bankpilot.db.assistant_repository import conversation_record, expire_turns, lock_owner
from bankpilot.db.models import (
    AssistantActionRecord,
    AssistantConversationRecord,
    AssistantTurnRecord,
)
from bankpilot.db.planning_repository import PlanningRepository
from bankpilot.domain.assistant import (
    ChatInput,
    ConversationDetail,
    ConversationPage,
    ConversationView,
    Message,
    TurnInput,
    TurnView,
)
from bankpilot.domain.planning import BudgetInput
from bankpilot.domain.spending import SpendingComparison, SpendingComparisonScope
from bankpilot.domain.transaction_search import SearchFilters
from bankpilot.errors import BankPilotError, PlanningError
from bankpilot.ports import AssistantGateway
from bankpilot.services.assistant import action_view, chat
from bankpilot.services.spending import compare_spending


async def database_now(session: AsyncSession) -> datetime:
    value: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()
    return value


def conversation_view(row: AssistantConversationRecord) -> ConversationView:
    return ConversationView.model_validate(
        {key: getattr(row, key) for key in ConversationView.model_fields}
    )


async def current_action(session: AsyncSession, row: AssistantActionRecord) -> dict[str, Any]:
    result = action_view(row)
    status = row.status
    if status == "pending":
        conversation = (
            await session.get(AssistantConversationRecord, row.conversation_id)
            if row.conversation_id
            else None
        )
        now = await database_now(session)
        if conversation is None or conversation.deleted:
            status = "unavailable"
        elif row.expires_at <= now:
            status = "expired"
        else:
            payload = BudgetInput.model_validate(row.payload)
            budget = await PlanningRepository(session).budget(
                row.user_id, payload.month, payload.category.value, payload.currency
            )
            if (budget.id if budget else None) != payload.budget_id or (
                budget.version if budget else 0
            ) != payload.expected_version:
                status = "conflict"
    result.update(
        effective_status=status,
        can_confirm=status == "pending",
        reason=None if status == "pending" else status,
    )
    return result


async def turn_view(session: AsyncSession, row: AssistantTurnRecord) -> TurnView:
    stored = dict(row.result) if row.result else {}
    request_summary = stored.get("request_summary", {})
    recompare_of = (
        request_summary.get("recompare_of") if isinstance(request_summary, dict) else None
    )
    reply = stored if stored and row.status == "completed" else None
    if reply and row.result_version != 3:
        reply = {
            "text": "",
            "evidence": [],
            "action": None,
            "assistant_result_unavailable": True,
        }
    elif reply and row.action_id:
        action = await session.get(AssistantActionRecord, row.action_id)
        reply["action"] = await current_action(session, action) if action else None
    return TurnView(
        **{
            key: getattr(row, key)
            for key in TurnView.model_fields
            if key not in {"reply", "recompare_of"}
        },
        recompare_of=recompare_of,
        reply=reply,
    )


class ConversationService:
    def __init__(self, factory: async_sessionmaker[AsyncSession], settings: Settings):
        self.factory = factory
        self.settings = settings

    async def reconcile(self) -> None:
        async with self.factory() as session:
            targets = (
                await session.execute(
                    select(AssistantConversationRecord.user_id, AssistantTurnRecord.conversation_id)
                    .join(AssistantTurnRecord)
                    .where(
                        AssistantTurnRecord.status == "processing",
                        AssistantTurnRecord.deadline <= func.clock_timestamp(),
                    )
                    .limit(100)
                )
            ).all()
        for uid, cid in targets:
            async with self.factory.begin() as session:
                await lock_owner(session, uid)
                row = await session.get(AssistantConversationRecord, cid)
                if row and not row.deleted:
                    await expire_turns(session, cid)

    async def recover_expired(self) -> None:
        while True:
            await asyncio.sleep(15)
            try:
                await self.reconcile()
            except SQLAlchemyError:
                logging.getLogger(__name__).warning("Assistant recovery database unavailable")

    async def submit(self, uid: UUID, payload: TurnInput, gateway: AssistantGateway) -> TurnView:
        digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        recompare_scope: SpendingComparisonScope | None = None
        async with self.factory.begin() as session:
            await lock_owner(session, uid)
            if payload.creation_id:
                row = await session.scalar(
                    select(AssistantConversationRecord).where(
                        AssistantConversationRecord.user_id == uid,
                        AssistantConversationRecord.creation_id == payload.creation_id,
                    )
                )
                if row and row.deleted:
                    raise PlanningError("assistant_conversation_deleted", 410)
                if row is None:
                    count = await session.scalar(
                        select(func.count())
                        .select_from(AssistantConversationRecord)
                        .where(
                            AssistantConversationRecord.user_id == uid,
                            AssistantConversationRecord.deleted.is_(False),
                        )
                    )
                    if count is not None and count >= self.settings.assistant_max_conversations:
                        raise PlanningError("assistant_conversation_limit", 409)
                    row = AssistantConversationRecord(
                        user_id=uid,
                        creation_id=payload.creation_id,
                        title=payload.question[:80],
                        month=payload.month,
                        scope=payload.spending_context.model_dump(mode="json")
                        if payload.spending_context
                        else None,
                    )
                    session.add(row)
                    await session.flush()
            else:
                assert payload.conversation_id is not None
                row = await conversation_record(session, uid, payload.conversation_id, lock=True)
            await expire_turns(session, row.id)
            old = await session.scalar(
                select(AssistantTurnRecord).where(
                    AssistantTurnRecord.conversation_id == row.id,
                    AssistantTurnRecord.request_id == payload.request_id,
                )
            )
            if old:
                if old.digest != digest:
                    raise PlanningError("assistant_request_conflict", 409)
                return await turn_view(session, old)
            if row.context_version != payload.expected_context_version:
                raise PlanningError("assistant_context_stale", 409)
            search_context = (
                SearchFilters.model_validate(row.search_context) if row.search_context else None
            )
            row.context_version += 1
            count = (
                await session.scalar(
                    select(func.count())
                    .select_from(AssistantTurnRecord)
                    .where(AssistantTurnRecord.conversation_id == row.id)
                )
                or 0
            )
            if payload.creation_id and count:
                raise PlanningError("assistant_request_conflict", 409)
            if count >= self.settings.assistant_max_turns:
                raise PlanningError("assistant_turn_limit", 409)
            processing = await session.scalar(
                select(AssistantTurnRecord.id).where(
                    AssistantTurnRecord.conversation_id == row.id,
                    AssistantTurnRecord.status == "processing",
                )
            )
            if processing:
                raise PlanningError("assistant_conversation_busy", 409)
            if payload.retry_of:
                original = await session.get(AssistantTurnRecord, payload.retry_of)
                if (
                    not original
                    or original.conversation_id != row.id
                    or original.status != "failed"
                ):
                    raise PlanningError("assistant_retry_invalid", 409)
            if payload.recompare_of:
                original = await session.get(AssistantTurnRecord, payload.recompare_of)
                if (
                    not original
                    or original.conversation_id != row.id
                    or original.status != "completed"
                    or original.result_version != 3
                ):
                    raise PlanningError("assistant_recompare_invalid", 409)
                comparison_items = [
                    item
                    for item in (original.result or {}).get("evidence", [])
                    if isinstance(item, dict) and item.get("tool") == "compare_spending"
                ]
                if len(comparison_items) != 1:
                    raise PlanningError("assistant_recompare_invalid", 409)
                try:
                    recompare_scope = SpendingComparison.model_validate(
                        comparison_items[0].get("data")
                    ).scope
                except ValueError as exc:
                    raise PlanningError("assistant_recompare_invalid", 409) from exc
            now = await database_now(session)
            turn_month = row.month if recompare_scope is not None else payload.month
            turn_scope = row.scope if recompare_scope is not None else (
                payload.spending_context.model_dump(mode="json")
                if payload.spending_context
                else None
            )
            if turn_month is None:
                raise PlanningError("assistant_recompare_invalid", 409)
            turn: AssistantTurnRecord | None = AssistantTurnRecord(
                conversation_id=row.id,
                search_context=row.search_context,
                result_version=3,
                request_id=payload.request_id,
                digest=digest,
                sequence=count + 1,
                question=payload.question,
                locale=payload.locale,
                month=turn_month,
                scope=turn_scope,
                business_date=now.astimezone(ZoneInfo(self.settings.business_timezone)).date(),
                retry_of=payload.retry_of,
                result={"request_summary": {"recompare_of": str(payload.recompare_of)}}
                if payload.recompare_of
                else None,
                deadline=now + timedelta(seconds=90),
            )
            assert turn is not None
            session.add(turn)
            if recompare_scope is None:
                row.month, row.scope = turn.month, turn.scope
            row.updated_at, row.accessed_at = now, now
            history = list(
                (
                    await session.scalars(
                        select(AssistantTurnRecord)
                        .where(
                            AssistantTurnRecord.conversation_id == row.id,
                            AssistantTurnRecord.status == "completed",
                            AssistantTurnRecord.result_version == 3,
                        )
                        .order_by(AssistantTurnRecord.sequence.desc())
                        .limit(7)
                    )
                ).all()
            )
            messages: list[Message] = []
            chars = len(payload.question)
            for previous in history:
                answer = str((previous.result or {}).get("text", ""))
                size = len(previous.question) + len(answer)
                if not answer or chars + size > self.settings.assistant_context_chars:
                    break
                messages[0:0] = [
                    Message(role="user", content=previous.question),
                    Message(role="assistant", content=answer),
                ]
                chars += size
            messages.append(Message(role="user", content=payload.question))
            await session.flush()
            cid, tid, token, today = row.id, turn.id, turn.completion_token, turn.business_date
        # No session/transaction spans model execution. Deadline is never renewed.
        try:
            async with asyncio.timeout(90):
                reply: dict[str, Any]
                if recompare_scope is not None:
                    async with self.factory() as session:
                        await session.connection(
                            execution_options={"isolation_level": "REPEATABLE READ"}
                        )
                        comparison = await compare_spending(
                            session, uid, recompare_scope, today
                        )
                    reply = {
                        "text": (
                            "已按当前日期重新比较，请核对新的实际范围。"
                            if payload.locale == "zh-CN"
                            else "Recomputed as of today. Review the updated date ranges."
                        ),
                        "evidence": [
                            {
                                "tool": "compare_spending",
                                "data": comparison.model_dump(mode="json"),
                            }
                        ],
                        "action": None,
                    }
                else:
                    reply = await chat(
                        self.factory,
                        gateway,
                        uid,
                        ChatInput(
                            messages=messages,
                            month=payload.month,
                            locale=payload.locale,
                            spending_context=payload.spending_context,
                            search_context=search_context,
                        ),
                        today,
                    )
                if payload.recompare_of:
                    reply["request_summary"] = {"recompare_of": str(payload.recompare_of)}
                if len(json.dumps(reply)) > self.settings.assistant_max_result_chars:
                    raise PlanningError("assistant_result_too_large", 422)
                async with self.factory.begin() as session:
                    await lock_owner(session, uid)
                    row = await conversation_record(session, uid, cid, lock=True)
                    await expire_turns(session, cid)
                    turn = await session.get(AssistantTurnRecord, tid)
                    if (
                        turn is None
                        or turn.status != "processing"
                        or turn.completion_token != token
                    ):
                        raise PlanningError("assistant_completion_expired", 409)
                    proposal = reply.pop("proposal", None)
                    if proposal:
                        action = AssistantActionRecord(
                            user_id=uid,
                            conversation_id=cid,
                            **proposal,
                            expires_at=(await database_now(session)) + timedelta(minutes=15),
                        )
                        session.add(action)
                        await session.flush()
                        turn.action_id = action.id
                    row.updated_at = await database_now(session)
                    await session.flush()
                    # Recheck database time at the final write, after proposal work.
                    completed = await session.scalar(
                        update(AssistantTurnRecord)
                        .where(
                            AssistantTurnRecord.id == tid,
                            AssistantTurnRecord.completion_token == token,
                            AssistantTurnRecord.status == "processing",
                            AssistantTurnRecord.deadline > func.clock_timestamp(),
                        )
                        .values(
                            status="completed", result=reply, completed_at=func.clock_timestamp()
                        )
                        .returning(AssistantTurnRecord.id)
                    )
                    if completed is None:
                        raise PlanningError("assistant_completion_expired", 409)
                    await session.refresh(turn)
                    result = await turn_view(session, turn)
                return result
        except (Exception, asyncio.CancelledError) as exc:
            code = getattr(
                exc,
                "code",
                "assistant_timeout"
                if isinstance(exc, (TimeoutError, asyncio.CancelledError))
                else "assistant_failed",
            )
            try:
                async with self.factory.begin() as session:
                    await lock_owner(session, uid)
                    turn = await session.get(AssistantTurnRecord, tid)
                    if turn and turn.status == "processing" and turn.completion_token == token:
                        turn.status, turn.error_code = "failed", code
                        turn.completed_at = await database_now(session)
            except SQLAlchemyError:
                pass  # Persistent deadline converges when the database returns.
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, (BankPilotError, PlanningError)):
                raise
            if isinstance(exc, TimeoutError):
                raise PlanningError("assistant_timeout", 504) from exc
            raise

    async def listing(self, uid: UUID, cursor: UUID | None) -> ConversationPage:
        async with self.factory() as session:
            base = select(AssistantConversationRecord).where(
                AssistantConversationRecord.user_id == uid,
                AssistantConversationRecord.deleted.is_(False),
            )
            recent = await session.scalar(
                base.order_by(AssistantConversationRecord.accessed_at.desc()).limit(1)
            )
            query = base
            if cursor:
                anchor = await session.get(AssistantConversationRecord, cursor)
                if not anchor or anchor.user_id != uid:
                    raise PlanningError("assistant_conversation_not_found", 404)
                query = query.where(
                    tuple_(AssistantConversationRecord.created_at, AssistantConversationRecord.id)
                    < (anchor.created_at, anchor.id)
                )
            rows = list(
                (
                    await session.scalars(
                        query.order_by(
                            AssistantConversationRecord.created_at.desc(),
                            AssistantConversationRecord.id.desc(),
                        ).limit(21)
                    )
                ).all()
            )
            return ConversationPage(
                items=[conversation_view(row) for row in rows[:20]],
                next_cursor=rows[19].id if len(rows) > 20 else None,
                recent_id=recent.id if recent else None,
            )

    async def detail(self, uid: UUID, cid: UUID, before: int | None = None) -> ConversationDetail:
        async with self.factory.begin() as session:
            await lock_owner(session, uid)
            row = await conversation_record(session, uid, cid, lock=True)
            await expire_turns(session, cid)
            row.accessed_at = await database_now(session)
            query = select(AssistantTurnRecord).where(AssistantTurnRecord.conversation_id == cid)
            if before:
                query = query.where(AssistantTurnRecord.sequence < before)
            turns = list(
                (
                    await session.scalars(
                        query.order_by(AssistantTurnRecord.sequence.desc()).limit(21)
                    )
                ).all()
            )
            return ConversationDetail(
                conversation=conversation_view(row),
                turns=[await turn_view(session, turn) for turn in reversed(turns[:20])],
                next_before=turns[19].sequence if len(turns) > 20 else None,
                turn_limit=self.settings.assistant_max_turns,
            )

    async def lookup(
        self, uid: UUID, request_id: UUID, cid: UUID | None, creation_id: UUID | None
    ) -> TurnView:
        async with self.factory.begin() as session:
            await lock_owner(session, uid)
            query = select(AssistantConversationRecord).where(
                AssistantConversationRecord.user_id == uid
            )
            query = (
                query.where(AssistantConversationRecord.id == cid)
                if cid
                else query.where(AssistantConversationRecord.creation_id == creation_id)
            )
            row = await session.scalar(query)
            if not row or row.deleted:
                raise PlanningError("assistant_request_not_found", 404)
            await expire_turns(session, row.id)
            turn = await session.scalar(
                select(AssistantTurnRecord).where(
                    AssistantTurnRecord.conversation_id == row.id,
                    AssistantTurnRecord.request_id == request_id,
                )
            )
            if not turn:
                raise PlanningError("assistant_request_not_found", 404)
            return await turn_view(session, turn)
