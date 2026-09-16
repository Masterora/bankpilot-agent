"""文件职责：在账户快照内统一预览和提交的四类计数。
关键边界：编号冲突整组拒绝，无编号出现次数由解析器保留；不提交事务。
"""

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.transaction_repository import TransactionRepository
from bankpilot.domain.statement_import import ParsedStatement, ParsedStatementRow, StatementRowError


@dataclass(frozen=True)
class ImportClassification:
    new: list[ParsedStatementRow]
    duplicates: list[ParsedStatementRow]
    errors: list[StatementRowError]

    @property
    def error_rows(self) -> int:
        return len({issue.row_number for issue in self.errors})


def facts(row: ParsedStatementRow) -> tuple[object, ...]:
    return (
        row.booking_date,
        row.occurred_at,
        row.amount,
        row.currency,
        row.merchant.casefold(),
        row.description.casefold(),
    )


async def classify_import(
    session: AsyncSession,
    parsed: ParsedStatement,
    account_id: UUID | None,
) -> ImportClassification:
    groups: dict[str, list[ParsedStatementRow]] = defaultdict(list)
    for row in parsed.rows:
        groups[row.fingerprint].append(row)
    repository = TransactionRepository(session)
    existing = (
        await repository.existing_fingerprints(
            account_id=account_id,
            fingerprints=set(groups),
        )
        if account_id
        else set()
    )
    conflicts = (
        set(
            await repository.conflicting_rows(
                account_id=account_id,
                rows=parsed.rows,
            )
        )
        if account_id
        else set()
    )
    new, duplicates, errors = [], [], list(parsed.errors)
    for fingerprint, rows in groups.items():
        if len({facts(row) for row in rows}) > 1 or any(
            row.row_number in conflicts for row in rows
        ):
            errors.extend(
                StatementRowError(
                    row.row_number,
                    "import_fact_conflict",
                    "相同交易编号的事实不一致，请核对原始账单",
                )
                for row in rows
            )
        elif fingerprint in existing:
            duplicates.extend(rows)
        else:
            new.append(rows[0])
            duplicates.extend(rows[1:])
    errors.sort(key=lambda issue: (issue.row_number, issue.code))
    result = ImportClassification(new, duplicates, errors)
    if parsed.total_rows != len(new) + len(duplicates) + result.error_rows + len(parsed.skipped):
        raise RuntimeError("Import row classification is inconsistent")
    return result
