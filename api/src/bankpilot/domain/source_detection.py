"""
文件职责：识别结构明确的交易 CSV 并生成字段映射。
主要内容：有限表头别名、分隔符检测和唯一列匹配。
关键边界：不依据文件名猜测银行；不确定字段返回失败，禁止模型猜测金额方向。
"""

import csv
import io

from bankpilot.domain.statement_import import StatementFieldMapping

ALIASES = {
    "occurred_at": {"date", "datetime", "交易日期", "日期", "交易时间"},
    "merchant": {"merchant", "counterparty", "交易对方", "商户", "对方"},
    "amount": {"amount", "金额", "交易金额"},
    "description": {"description", "memo", "note", "说明", "摘要", "备注"},
    "transaction_id": {"transaction_id", "交易编号", "流水号"},
    "account": {"account", "账户", "账户名称"},
    "currency": {"currency", "币种"},
}


def detect_mapping(content: str) -> StatementFieldMapping:
    """只接受唯一匹配的结构；表头外说明、独立收支列需来源适配器处理。"""
    content = content.removeprefix("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(content[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    headers = next(csv.reader(io.StringIO(content), dialect=dialect), [])
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


def detect_account(content: str, mapping: StatementFieldMapping) -> tuple[str | None, str | None]:
    """仅从全文件一致的显式账户与币种列提取元数据，不从文件名推断身份。"""
    content = content.removeprefix("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(content[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(content), dialect=dialect))
    values: list[str | None] = []
    for column in (mapping.account, mapping.currency):
        if column is None:
            values.append(None)
            continue
        unique = {" ".join((row.get(column) or "").split()) for row in rows}
        if len(unique) != 1 or "" in unique:
            raise ValueError("Statement must contain one consistent account and currency")
        values.append(next(iter(unique)))
    return values[0], values[1].upper() if values[1] else None
