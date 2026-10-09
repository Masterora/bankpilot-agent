"""Export user-owned data and explicitly confirmed account deletion.

Exports are bounded consistent snapshots, excluding authentication material and shared
security records. Deletion uses the existing user lock and database cascades.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.base import Base
from bankpilot.db.models import (
    AssistantConversationRecord,
    AssistantTurnRecord,
    MonthlyReportRecord,
    RunRecord,
    UserRecord,
)
from bankpilot.db.user_repository import SessionRepository, UserRepository
from bankpilot.errors import PlanningError
from bankpilot.security import verify_password_async


async def export_account(session: AsyncSession, uid: UUID) -> dict[str, object]:
    # Explicit ownership roots. Child tables lacking user_id are reached only through
    # their owning account/run/conversation, never through arbitrary relationship links.
    roots = {
        "cards": "accounts",
        "transactions": "accounts",
        "audit_events": "runs",
        "assistant_turns": "assistant_conversations",
        "recurring_revisions": "recurring_plans",
        "recurring_skips": "recurring_plans",
        "recurring_matches": "recurring_plans",
    }
    data: dict[str, object] = {}
    remaining = 50_000
    size = 0
    for table in Base.metadata.sorted_tables:
        if table.name in {"sessions", "security_budgets", "security_leases"}:
            continue
        columns = [column for column in table.c if column.name != "password_hash"]
        if table.name == "users":
            predicate = table.c.id == uid
        elif "user_id" in table.c:
            predicate = table.c.user_id == uid
        elif table.name in roots:
            owner = Base.metadata.tables[roots[table.name]]
            fk = next(fk for fk in table.foreign_keys if fk.column.table is owner)
            predicate = fk.parent.in_(select(owner.c.id).where(owner.c.user_id == uid))
        else:
            raise PlanningError("account_export_unsupported", 503)
        statement = (
            select(*columns)
            .where(predicate)
            .order_by(*table.primary_key.columns)
            .limit(remaining + 1)
            .execution_options(yield_per=10)
        )
        records = []
        async for row in (await session.stream(statement)).mappings():
            if remaining == 0:
                raise PlanningError("account_export_capacity", 422)
            remaining -= 1
            encoded = jsonable_encoder(dict(row), custom_encoder={Decimal: str})
            size += len(json.dumps(encoded, ensure_ascii=False).encode())
            if size > 20 * 1024 * 1024:
                raise PlanningError("account_export_capacity", 422)
            records.append(encoded)
        data[table.name] = records
    result: dict[str, object] = {
        "format": "bankpilot-account-v1",
        "exported_at": datetime.now(UTC).isoformat(),
        "data": data,
    }
    if len(json.dumps(result, ensure_ascii=False).encode()) > 20 * 1024 * 1024:
        raise PlanningError("account_export_capacity", 422)
    return result


async def delete_account(
    session: AsyncSession,
    uid: UUID,
    token_hash: str,
    current_password: str,
) -> None:
    # Password work holds no database connection. Revalidate both the current hash
    # and session under the user lock before any destructive statement.
    candidate = await session.get(UserRecord, uid)
    if candidate is None:
        raise PlanningError("session_expired", 401)
    expected_hash = candidate.password_hash
    await session.rollback()
    valid = await verify_password_async(current_password, expected_hash)
    await UserRepository(session).lock(uid)
    user = await SessionRepository(session).resolve_user(token_hash)
    if user is None or user.id != uid or user.password_hash != expected_hash:
        raise PlanningError("session_expired", 401)
    if not valid:
        raise PlanningError("current_password_invalid", 400)
    pending = [
        select(RunRecord.id).where(
            # UNKNOWN seals an interrupted read-only run; its old worker cannot
            # complete it. It must not permanently prevent account deletion.
            RunRecord.user_id == uid, RunRecord.status.not_in(["SUCCEEDED", "FAILED", "UNKNOWN"])
        ),
        select(MonthlyReportRecord.id).where(
            MonthlyReportRecord.user_id == uid,
            MonthlyReportRecord.status.in_(["QUEUED", "RUNNING"]),
        ),
        select(AssistantTurnRecord.id)
        .join(AssistantConversationRecord)
        .where(
            AssistantConversationRecord.user_id == uid, AssistantTurnRecord.status == "processing"
        ),
    ]
    for query in pending:
        if await session.scalar(select(exists(query))):
            raise PlanningError("account_work_pending", 409)
    # Turns reference actions with a non-cascading FK. Clear this user's turns first
    # so PostgreSQL's immediate action cascade cannot encounter a live reference.
    await session.execute(
        delete(AssistantTurnRecord).where(
            AssistantTurnRecord.conversation_id.in_(
                select(AssistantConversationRecord.id).where(
                    AssistantConversationRecord.user_id == uid
                )
            )
        )
    )
    await session.execute(delete(UserRecord).where(UserRecord.id == uid))
