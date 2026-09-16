"""文件职责：编排可恢复的账单导入。
关键边界：读取释放连接后解析，用户锁内重查操作身份；批次、账户和流水原子提交。
"""

import hashlib
import json
from dataclasses import asdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from bankpilot.db.import_repository import ImportRepository
from bankpilot.db.ledger_revision import bump_revision
from bankpilot.db.models import AccountRecord, ImportBatchRecord, UserRecord
from bankpilot.db.transaction_repository import TransactionRepository
from bankpilot.domain.payment_sources import source_account
from bankpilot.domain.statement_import import (
    ParsedStatement,
    StatementFieldMapping,
    parse_statement_csv,
)
from bankpilot.errors import ImportConflictError
from bankpilot.observability import measure
from bankpilot.services.accounts import resolve_account
from bankpilot.services.import_classification import classify_import


def request_digest(
    *,
    file_name: str,
    content: str,
    account_name: str,
    currency: str,
    mapping: StatementFieldMapping,
    account_id: UUID | None,
) -> str:
    data = dict(
        file_name=file_name,
        content=content,
        account_name=account_name,
        currency=currency,
        mapping=mapping.model_dump(),
        account_id=str(account_id) if account_id else None,
    )
    return hashlib.sha256(
        json.dumps(
            data,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def parse_input(
    content: str,
    mapping: StatementFieldMapping,
    currency: str,
    name: str,
    account_id: UUID | None,
) -> tuple[ParsedStatement, str]:
    """CPU 与来源扫描不持数据库连接。"""
    with measure("parse_ms"):
        parsed = parse_statement_csv(content=content, mapping=mapping, currency=currency)
        return parsed, source_account(parsed.source, name) if account_id is None else name


class StatementImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def execute(
        self,
        *,
        user_id: UUID,
        idempotency_key: UUID,
        file_name: str,
        content: str,
        account_name: str,
        currency: str,
        mapping: StatementFieldMapping,
        account_id: UUID | None = None,
    ) -> tuple[ImportBatchRecord, bool]:
        digest = request_digest(
            file_name=file_name,
            content=content,
            account_name=account_name,
            currency=currency,
            mapping=mapping,
            account_id=account_id,
        )
        imports = ImportRepository(self.session)
        with measure("connection_ms"):
            await self.session.connection()
        old = await imports.by_key(user_id, idempotency_key)
        if old:
            self.session.expunge(old)
        await self.session.rollback()
        if old:
            if old.request_digest != digest:
                raise ImportConflictError
            return old, True
        parsed, inferred_name = await run_in_threadpool(
            parse_input, content, mapping, currency, account_name, account_id
        )
        if account_id is None:
            account_name = inferred_name
        async with self.session.begin():
            with measure("connection_ms"):
                await self.session.connection()
            if (
                await self.session.scalar(
                    select(UserRecord.id).where(UserRecord.id == user_id).with_for_update()
                )
                is None
            ):
                raise ValueError("User is unavailable")
            old = await imports.by_key(user_id, idempotency_key)
            if old:
                if old.request_digest != digest:
                    raise ImportConflictError
                self.session.expunge(old)
                return old, True
            account = await resolve_account(
                self.session,
                user_id=user_id,
                account_id=account_id,
                name=account_name,
                currency=currency,
                source=parsed.source,
            )
            classified = await classify_import(
                self.session, parsed, account.id if account else None
            )
            rejected = bool(classified.errors)
            if not rejected and classified.new and account is None:
                account = AccountRecord(
                    user_id=user_id, name=account_name, currency=currency, source=parsed.source
                )
                self.session.add(account)
                await self.session.flush()
            dates = [row.booking_date for row in parsed.rows]
            mapping_data = mapping.model_dump()
            mapping_data["source"] = parsed.source
            batch = await imports.add(
                user_id=user_id,
                idempotency_key=idempotency_key,
                request_digest=digest,
                parser_version=parsed.parser_version,
                new_rows=len(classified.new),
                skipped_rows=len(parsed.skipped),
                issue_count=len(classified.errors),
                account_id=account.id if account else None,
                account_name=account.name if account else account_name,
                currency=currency,
                file_name=file_name,
                file_hash=parsed.file_hash,
                status="REJECTED"
                if rejected
                else ("COMPLETED_WITH_DUPLICATES" if classified.duplicates else "COMPLETED"),
                total_rows=parsed.total_rows,
                imported_rows=0 if rejected else len(classified.new),
                duplicate_rows=len(classified.duplicates),
                error_rows=classified.error_rows,
                start_date=min(dates) if dates else None,
                end_date=max(dates) if dates else None,
                field_mapping=mapping_data,
                errors=[asdict(e) for e in classified.errors[:100]]
                + [asdict(e) for e in sorted(parsed.skipped, key=lambda e: e.row_number)[:100]],
            )
            if not rejected and classified.new:
                assert account is not None
                await TransactionRepository(self.session).add_imported(
                    account_id=account.id,
                    import_batch_id=batch.id,
                    rows=classified.new,
                )
                await bump_revision(self.session, user_id)
            self.session.expunge(batch)
        return batch, False
