"""
文件职责：识别结构明确的交易 CSV 并生成字段映射。
主要内容：有限表头别名、分隔符检测和唯一列匹配。
关键边界：不依据文件名猜测银行；不确定字段返回失败，禁止模型猜测金额方向。
"""

import csv
import io
from dataclasses import dataclass

from bankpilot.domain.payment_sources import locate_source
from bankpilot.domain.statement_import import PARSER_VERSION, StatementFieldMapping

ALIASES = {
    "occurred_at": {"date", "datetime", "交易日期", "日期", "交易时间"},
    "merchant": {"merchant", "counterparty", "交易对方", "商户", "对方"},
    "amount": {"amount", "金额", "交易金额"},
    "description": {"description", "memo", "note", "说明", "摘要", "备注"},
    "transaction_id": {"transaction_id", "交易编号", "流水号"},
    "account": {"account", "账户", "账户名称"},
    "currency": {"currency", "币种"},
}


@dataclass(frozen=True)
class DetectedStatement:
    source: str
    parser_version: str
    headers: list[str]
    mapping: StatementFieldMapping
    account_name: str | None
    currency: str | None


def detect_statement(content: str) -> DetectedStatement:
    """一次来源定位和 CSV 读取产生完整识别结果，不重复扫描文件。"""
    native = locate_source(content)
    if native is not None:
        profile = native.profile
        return DetectedStatement(
            source=profile.key,
            parser_version=profile.parser_version,
            headers=native.headers,
            mapping=StatementFieldMapping(
                occurred_at=profile.time,
                merchant=profile.merchant,
                amount=profile.amount,
                description=profile.description,
                transaction_id=profile.identifier,
            ),
            account_name=None,
            currency="CNY",
        )
    content = content.removeprefix("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(content[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    headers = list(reader.fieldnames or [])
    mapping = _detect_mapping(headers)
    account_name, currency = _detect_account(reader, mapping)
    return DetectedStatement(
        "standard", PARSER_VERSION, headers, mapping, account_name, currency
    )


def _detect_mapping(headers: list[str]) -> StatementFieldMapping:
    """只接受唯一匹配的结构，独立收支列需来源适配器处理。"""
    fields: dict[str, str | None] = {}
    if any(
        header.strip().lower()
        in {
            "收/支",
            "收支",
            "收入",
            "支出",
            "借方",
            "贷方",
            "收支方向",
            "收支类型",
            "交易状态",
            "当前状态",
            "退款金额",
            "status",
            "direction",
        }
        for header in headers
    ):
        raise ValueError("This statement requires a source-specific semantics adapter")
    for name, aliases in ALIASES.items():
        matches = [header for header in headers if header.strip().lower() in aliases]
        if len(matches) > 1 or (not matches and name in {"occurred_at", "merchant", "amount"}):
            raise ValueError("Statement format is not recognized")
        fields[name] = matches[0] if matches else None
    return StatementFieldMapping.model_validate(fields)


def _detect_account(
    rows: csv.DictReader[str], mapping: StatementFieldMapping
) -> tuple[str | None, str | None]:
    """从同一次 CSV 读取中提取一致的账户/币种，不保留全量记录。"""
    columns = (mapping.account, mapping.currency)
    if not any(columns):
        return None, None
    unique: list[set[str]] = [set(), set()]
    for row in rows:
        for index, column in enumerate(columns):
            if column is not None:
                unique[index].add(" ".join((row.get(column) or "").split()))
    values: list[str | None] = []
    for column, entries in zip(columns, unique, strict=True):
        if column is None:
            values.append(None)
        elif len(entries) != 1 or "" in entries:
            raise ValueError("Statement must contain one consistent account and currency")
        else:
            values.append(next(iter(entries)))
    return values[0], values[1].upper() if values[1] else None
