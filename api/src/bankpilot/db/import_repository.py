"""
文件职责：封装账单导入批次持久化。
主要内容：创建批次、按用户倒序读取历史、按用户与操作幂等键查找已提交结果。
关键边界：只参与调用方事务，不隐式提交或补造来源字段。
"""
from datetime import date
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import ImportBatchRecord


class ImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        user_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
        parser_version: str,
        new_rows: int,
        skipped_rows: int,
        issue_count: int,
        account_id: UUID | None,
        account_name: str,
        currency: str,
        file_name: str,
        file_hash: str,
        status: str,
        total_rows: int,
        imported_rows: int,
        duplicate_rows: int,
        error_rows: int,
        start_date: date | None,
        end_date: date | None,
        field_mapping: dict[str, str | None],
        errors: list[dict[str, Any]],
    ) -> ImportBatchRecord:
        batch = ImportBatchRecord(
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            parser_version=parser_version,
            new_rows=new_rows,
            skipped_rows=skipped_rows,
            issue_count=issue_count,
            account_id=account_id,
            account_name=account_name,
            currency=currency,
            file_name=file_name,
            file_hash=file_hash,
            status=status,
            total_rows=total_rows,
            imported_rows=imported_rows,
            duplicate_rows=duplicate_rows,
            error_rows=error_rows,
            start_date=start_date,
            end_date=end_date,
            field_mapping=field_mapping,
            errors=errors,
        )
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def list_for_user(self, user_id: UUID) -> list[ImportBatchRecord]:
        records = await self.session.scalars(
            select(ImportBatchRecord)
            .where(ImportBatchRecord.user_id == user_id)
            .order_by(ImportBatchRecord.created_at.desc(), ImportBatchRecord.id.desc())
        )
        return list(records)

    async def by_key(self, user_id: UUID, key: UUID) -> ImportBatchRecord | None:
        return cast(
            ImportBatchRecord | None,
            await self.session.scalar(
                select(ImportBatchRecord).where(
                    ImportBatchRecord.user_id == user_id,
                    ImportBatchRecord.idempotency_key == key,
                )
            ),
        )
