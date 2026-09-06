"""
文件职责：编排一次账单导入的解析、账户归属、去重、批次报告和原子写入。

主要内容：`StatementImportService.execute` 将确定性解析结果转换为持久化批次与标准交易。
关键边界：失败行只生成拒绝报告；有效批次在同一事务写入账户、报告和交易；并发冲突转为稳定业务异常。
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.models import AccountRecord, ImportBatchRecord, UserRecord
from bankpilot.db.repositories import ImportRepository, TransactionRepository
from bankpilot.domain.payment_sources import source_account
from bankpilot.domain.statement_import import StatementFieldMapping, parse_statement_csv
from bankpilot.errors import ImportConflictError
from bankpilot.services.accounts import resolve_account


class StatementImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def execute(
        self,
        *,
        user_id: UUID,
        file_name: str,
        content: str,
        account_name: str,
        currency: str,
        mapping: StatementFieldMapping,
        account_id: UUID | None = None,
    ) -> ImportBatchRecord:
        """整批校验并持久化；调用前应结束身份查询产生的只读事务。"""
        parsed = parse_statement_csv(content=content, mapping=mapping, currency=currency)
        mapping_data = mapping.model_dump()
        mapping_data["source"] = parsed.source
        if account_id is None:
            account_name = source_account(content, account_name)
        exclusions = [
            {"row_number": item.row_number, "code": item.code, "message": item.message}
            for item in parsed.skipped
        ]
        row_errors = [
            {"row_number": error.row_number, "code": error.code, "message": error.message}
            for error in parsed.errors[:100]
        ]
        parsed_dates = [row.booking_date for row in parsed.rows]

        try:
            async with self.session.begin():
                await self.session.scalar(
                    select(UserRecord).where(UserRecord.id == user_id).with_for_update()
                )
                imports = ImportRepository(self.session)
                account = await resolve_account(
                    self.session,
                    user_id=user_id,
                    account_id=account_id,
                    name=account_name,
                    currency=currency,
                    source=parsed.source,
                )
                if parsed.errors:
                    batch = await imports.add(
                        user_id=user_id,
                        account_id=None,
                        account_name=account_name,
                        currency=currency,
                        file_name=file_name,
                        file_hash=parsed.file_hash,
                        status="REJECTED",
                        total_rows=parsed.total_rows,
                        imported_rows=0,
                        duplicate_rows=0,
                        error_rows=len(parsed.errors),
                        start_date=min(parsed_dates) if parsed_dates else None,
                        end_date=max(parsed_dates) if parsed_dates else None,
                        field_mapping=mapping_data,
                        errors=row_errors + exclusions,
                    )
                else:
                    if account is None:
                        account = AccountRecord(
                            user_id=user_id,
                            name=account_name,
                            currency=currency,
                            source=parsed.source.partition(":")[0],
                        )
                        self.session.add(account)
                        await self.session.flush()
                    transactions = TransactionRepository(self.session)
                    if await transactions.conflicting_rows(account_id=account.id, rows=parsed.rows):
                        raise ImportConflictError
                    existing = await transactions.existing_fingerprints(
                        account_id=account.id,
                        fingerprints={row.fingerprint for row in parsed.rows},
                    )
                    new_rows = [row for row in parsed.rows if row.fingerprint not in existing]
                    batch = await imports.add(
                        user_id=user_id,
                        account_id=account.id,
                        account_name=account.name,
                        currency=account.currency,
                        file_name=file_name,
                        file_hash=parsed.file_hash,
                        status="COMPLETED_WITH_DUPLICATES" if existing else "COMPLETED",
                        total_rows=parsed.total_rows,
                        imported_rows=len(new_rows),
                        duplicate_rows=len(parsed.rows) - len(new_rows),
                        error_rows=0,
                        start_date=min(parsed_dates) if parsed_dates else None,
                        end_date=max(parsed_dates) if parsed_dates else None,
                        field_mapping=mapping_data,
                        errors=exclusions,
                    )
                    await transactions.add_imported(
                        account_id=account.id,
                        import_batch_id=batch.id,
                        rows=new_rows,
                    )
        except IntegrityError as exc:
            raise ImportConflictError from exc

        await self.session.refresh(batch)
        return batch
