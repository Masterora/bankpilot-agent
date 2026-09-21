"""
文件职责：编排原始账本的完整匹配、分页、详情和 CSV 转换。
主要内容：验证账户与批次归属、检查双版本、匹配文本与分类、装配已确认关系标签及安全导出。
关键边界：调用方拥有可重复读快照；超限拒绝部分结果，关系标签不剔除原始流水，文本导出防止公式执行。
"""
from datetime import UTC
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.adapters.local_banking import LocalBankingGateway
from bankpilot.db.models import AccountRecord, ImportBatchRecord, TransactionRelationRecord
from bankpilot.db.transaction_repository import TransactionRepository
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.transaction_search import (
    CAPACITY,
    PAGE_SIZE,
    SEARCH_VERSION,
    SearchDetail,
    SearchFilters,
    SearchItem,
    SearchPage,
    SearchRequest,
    normalize_text,
)
from bankpilot.errors import PlanningError


async def validate_ownership(session: AsyncSession, uid: UUID, filters: SearchFilters) -> None:
    for model, identity in (
        (AccountRecord, filters.account_id),
        (ImportBatchRecord, filters.import_batch_id),
    ):
        if identity is not None:
            found = await session.scalar(
                select(model.id).where(model.id == identity, model.user_id == uid)
            )
            if found is None:
                raise PlanningError("search_filter_unavailable", 404)


async def check_version(
    session: AsyncSession, uid: UUID, expected: int | None, version: str | None
) -> int:
    revision = await UserRepository(session).ledger_revision(uid)
    if revision is None:
        raise PlanningError("user_not_found", 404)
    if (expected is None) != (version is None):
        raise PlanningError("invalid_request", 422)
    if expected is not None and (revision != expected or version != SEARCH_VERSION):
        raise PlanningError("search_stale", 409)
    return revision


async def attach_relations(session: AsyncSession, uid: UUID, items: list[SearchItem]) -> None:
    # Only confirmed facts, including relationships whose counterpart is outside this search.
    by_id = {item.id: item for item in items}
    if not by_id:
        return
    relations = await session.scalars(
        select(TransactionRelationRecord).where(
            TransactionRelationRecord.user_id == uid,
            TransactionRelationRecord.state == "confirmed",
            or_(
                TransactionRelationRecord.first_id.in_(by_id),
                TransactionRelationRecord.second_id.in_(by_id),
            ),
        )
    )
    for relation in relations:
        for identity in (relation.first_id, relation.second_id):
            if identity in by_id and relation.kind not in by_id[identity].relation_kinds:
                by_id[identity].relation_kinds.append(relation.kind)
    for item in items:
        item.relation_kinds.sort()


async def matching_items(
    session: AsyncSession, uid: UUID, filters: SearchFilters
) -> list[SearchItem]:
    await validate_ownership(session, uid, filters)
    rows = await TransactionRepository(session).search_rows(uid, filters)
    if len(rows) > CAPACITY:
        raise PlanningError("search_capacity_exceeded", 422)
    items = []
    for row, name, override in rows:
        base = LocalBankingGateway._to_item(row, name, override)
        if filters.category is not None and base.category != filters.category:
            continue
        fields = [row.merchant]
        if filters.text_scope == "merchant_or_note":
            fields.append(row.description)
        if filters.text and not any(filters.text in normalize_text(value) for value in fields):
            continue
        items.append(SearchItem(**base.model_dump(), account_id=row.account_id))
    return items


async def search(session: AsyncSession, uid: UUID, request: SearchRequest) -> SearchPage:
    revision = await check_version(
        session, uid, request.expected_revision, request.expected_search_version
    )
    items = await matching_items(session, uid, request.filters)
    page = items[request.offset : request.offset + PAGE_SIZE]
    await attach_relations(session, uid, page)
    return SearchPage(
        filters=request.filters,
        total_count=len(items),
        items=page,
        offset=request.offset,
        has_more=request.offset + PAGE_SIZE < len(items),
        ledger_revision=revision,
    )


async def detail(
    session: AsyncSession, uid: UUID, identity: UUID, expected: int | None, version: str | None
) -> SearchDetail:
    revision = await check_version(session, uid, expected, version)
    rows = await TransactionRepository(session).search_rows(uid, transaction_id=identity)
    if not rows:
        raise PlanningError("transaction_not_found", 404)
    row, name, override = rows[0]
    item = SearchItem(
        **LocalBankingGateway._to_item(row, name, override).model_dump(), account_id=row.account_id
    )
    await attach_relations(session, uid, [item])
    return SearchDetail(item=item, ledger_revision=revision)


def export_csv(items: list[SearchItem]) -> str:
    def cell(value: str) -> str:
        if value.lstrip().startswith(("=", "+", "@", "-")):
            value = "'" + value
        return '"' + value.replace('"', '""') + '"'

    rows = [
        "Date,Time UTC,Precision,Account,Merchant,Amount,Currency,Category,"
        "Batch,Source row,Description"
    ]
    for item in items:
        time = (
            item.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if item.time_precision == "timestamp"
            else ""
        )
        rows.append(
            ",".join(
                [
                    cell(str(item.booking_date)),
                    cell(time),
                    cell(item.time_precision),
                    cell(item.account_name),
                    cell(item.merchant),
                    str(item.amount),
                    cell(item.currency),
                    cell(item.category),
                    cell(str(item.import_batch_id or "")),
                    str(item.source_row_number or ""),
                    cell(item.description),
                ]
            )
        )
    return "\ufeff" + "\r\n".join(rows)
