"""
文件职责：将用户提供的 CSV 账单确定性解析为可写入的标准交易。

主要内容：
- `StatementFieldMapping`：声明源表头与标准字段的对应关系。
- `parse_statement_csv`：检测分隔符、校验全部行并生成稳定行指纹。
- `ParsedStatement` / `StatementRowError`：返回有效交易或可展示的失败原因。

关键边界：本模块不访问数据库、不调用模型、不保存源文件；任一失败行都由应用层阻止整批写入。
"""

import csv
import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bankpilot.domain.payment_sources import locate_source, normalize_row

MAX_STATEMENT_ROWS = 5_000


class StatementFieldMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurred_at: str = Field(min_length=1, max_length=120)
    merchant: str = Field(min_length=1, max_length=120)
    amount: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=120)
    transaction_id: str | None = Field(default=None, min_length=1, max_length=120)
    account: str | None = Field(default=None, min_length=1, max_length=120)
    currency: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def fields_must_be_distinct(self) -> "StatementFieldMapping":
        """禁止一个源列同时承担多个标准字段，避免静默误映射。"""
        selected = [self.occurred_at, self.merchant, self.amount]
        selected.extend(
            value
            for value in (self.description, self.transaction_id, self.account, self.currency)
            if value is not None
        )
        if len(selected) != len(set(selected)):
            raise ValueError("mapped source columns must be distinct")
        return self


@dataclass(frozen=True)
class ParsedStatementRow:
    row_number: int
    booking_date: date
    occurred_at: datetime
    merchant: str
    description: str
    amount: Decimal
    currency: str
    fingerprint: str
    time_precision: str = "unknown"


@dataclass(frozen=True)
class StatementRowError:
    row_number: int
    code: str
    message: str


@dataclass(frozen=True)
class ParsedStatement:
    file_hash: str
    total_rows: int
    rows: list[ParsedStatementRow]
    errors: list[StatementRowError]
    source: str = "standard"
    skipped: list[StatementRowError] = field(default_factory=list)


def parse_statement_csv(
    *, content: str, mapping: StatementFieldMapping, currency: str
) -> ParsedStatement:
    """将 CSV 读取错误统一转换为拒绝报告，包含超长表头和字段。"""
    try:
        native = _parse_payment_source(content, currency)
        if native is not None:
            return native
        return _parse_statement_csv(content=content, mapping=mapping, currency=currency)
    except (csv.Error, ValueError) as exc:
        digest = hashlib.sha256(content.removeprefix("\ufeff").encode()).hexdigest()
        return ParsedStatement(
            digest,
            0,
            [],
            [StatementRowError(1, "INVALID_ROW", str(exc) or "CSV structure is invalid")],
        )


def _parse_payment_source(content: str, currency: str) -> ParsedStatement | None:
    """来源解析复用金额与编号校验，映射错误和排除行回到原文件行号。"""
    table = locate_source(content)
    if table is None:
        return None
    if currency != "CNY":
        raise ValueError("个人支付账单币种必须为 CNY")
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["date", "merchant", "amount", "description", "transaction_id"])
    numbers: list[int] = []
    errors: list[StatementRowError] = []
    skipped: list[StatementRowError] = []
    total = 0
    for number, cells in table.rows:
        if not any(v.strip() for v in cells):
            continue
        if cells[0].strip().startswith(("---", "共", "导出时间", "温馨提示")):
            continue
        total += 1
        if total > MAX_STATEMENT_ROWS:
            raise ValueError("Statement exceeds the 5000 row limit")
        while len(cells) > len(table.headers) and not cells[-1].strip():
            cells = cells[:-1]
        # 工作表省略尾部空单元格；补空后仍由必填字段校验禁止缺失交易依据。
        if len(cells) < len(table.headers):
            cells = cells + [""] * (len(table.headers) - len(cells))
        try:
            if len(cells) != len(table.headers):
                raise ValueError("源行列数与表头不一致")
            row = dict(zip(table.headers, cells, strict=True))
            result = normalize_row(table.profile, row)
            if result is None:
                skipped.append(
                    StatementRowError(
                        number,
                        "EXCLUDED",
                        f"未入账：{row[table.profile.status].strip()} / {row['收/支'].strip()}",
                    )
                )
                continue
            writer.writerow(result)
            numbers.append(number)
        except ValueError as exc:
            errors.append(StatementRowError(number, "INVALID_ROW", str(exc)))
    parsed = _parse_statement_csv(
        content=stream.getvalue(),
        currency=currency,
        mapping=StatementFieldMapping(
            occurred_at="date",
            merchant="merchant",
            amount="amount",
            description="description",
            transaction_id="transaction_id",
        ),
    )
    if numbers:
        errors.extend(replace(e, row_number=numbers[e.row_number - 2]) for e in parsed.errors)
    elif total == 0:
        errors.append(StatementRowError(1, "NO_DATA_ROWS", "没有交易行"))
    return ParsedStatement(
        hashlib.sha256(content.encode()).hexdigest(),
        total,
        [replace(row, row_number=numbers[row.row_number - 2]) for row in parsed.rows],
        errors,
        table.profile.key + ":1",
        skipped,
    )


def _parse_statement_csv(
    *, content: str, mapping: StatementFieldMapping, currency: str
) -> ParsedStatement:
    """完整解析 CSV；错误行与有效行同时返回，由调用方执行整批接受或拒绝。"""
    normalized_content = content.removeprefix("\ufeff")
    file_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
    if not normalized_content.strip():
        return ParsedStatement(
            file_hash=file_hash,
            total_rows=0,
            rows=[],
            errors=[StatementRowError(1, "EMPTY_FILE", "CSV file is empty")],
        )
    if "\ufffd" in normalized_content or "\x00" in normalized_content:
        return ParsedStatement(
            file_hash=file_hash,
            total_rows=0,
            rows=[],
            errors=[StatementRowError(1, "INVALID_ENCODING", "CSV contains undecodable text")],
        )

    try:
        dialect = csv.Sniffer().sniff(normalized_content[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(normalized_content, newline=""), dialect=dialect)
    headers = reader.fieldnames or []
    if any(h.strip() in {"收/支", "收支方向", "交易状态", "当前状态", "退款金额"} for h in headers):
        raise ValueError("来源结构未适配，禁止按通用金额列推断收支")
    if len(headers) != len(set(headers)):
        return ParsedStatement(
            file_hash=file_hash,
            total_rows=0,
            rows=[],
            errors=[StatementRowError(1, "DUPLICATE_HEADER", "CSV headers must be unique")],
        )
    required_headers = [mapping.occurred_at, mapping.merchant, mapping.amount]
    required_headers.extend(
        value
        for value in (
            mapping.description,
            mapping.transaction_id,
            mapping.account,
            mapping.currency,
        )
        if value is not None
    )
    missing_headers = [header for header in required_headers if header not in headers]
    if missing_headers:
        return ParsedStatement(
            file_hash=file_hash,
            total_rows=0,
            rows=[],
            errors=[
                StatementRowError(
                    1,
                    "MISSING_COLUMN",
                    f"Missing mapped columns: {', '.join(missing_headers)}",
                )
            ],
        )

    try:
        raw_rows = list(reader)
    except csv.Error:
        return ParsedStatement(
            file_hash,
            0,
            [],
            [
                StatementRowError(
                    reader.line_num, "INVALID_ROW", "CSV structure or field size is invalid"
                )
            ],
        )
    if not raw_rows:
        return ParsedStatement(
            file_hash=file_hash,
            total_rows=0,
            rows=[],
            errors=[StatementRowError(2, "NO_DATA_ROWS", "CSV has no transaction rows")],
        )
    if len(raw_rows) > MAX_STATEMENT_ROWS:
        return ParsedStatement(
            file_hash=file_hash,
            total_rows=len(raw_rows),
            rows=[],
            errors=[
                StatementRowError(
                    1,
                    "TOO_MANY_ROWS",
                    f"CSV exceeds the {MAX_STATEMENT_ROWS} row limit",
                )
            ],
        )

    parsed_rows: list[ParsedStatementRow] = []
    errors: list[StatementRowError] = []
    occurrence_counts: defaultdict[str, int] = defaultdict(int)
    identifiers: dict[str, str] = {}
    account_names: set[str] = set()
    for row_number, raw in enumerate(raw_rows, start=2):
        try:
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError("row column count does not match the CSV header")
            booking_date, occurred_at = _parse_datetime(raw.get(mapping.occurred_at, ""))
            merchant = _required_text(raw.get(mapping.merchant, ""), "merchant", 160)
            description = _optional_text(
                raw.get(mapping.description, "") if mapping.description else "", 500
            )
            amount = _parse_amount(raw.get(mapping.amount, ""))
            if mapping.currency and raw[mapping.currency].strip().upper() != currency:
                raise ValueError("currency differs from the selected account currency")
            if mapping.account:
                account_names.add(_required_text(raw[mapping.account], "account", 100))
                if len(account_names) > 1:
                    raise ValueError("one statement must contain only one account")
            canonical = "\x1f".join(
                [
                    booking_date.isoformat(),
                    occurred_at.isoformat(),
                    merchant.casefold(),
                    description.casefold(),
                    format(amount, ".2f"),
                    currency,
                ]
            )
            # 同一文件中完全相同的真实交易按出现次序保留；重复导入时指纹仍保持稳定。
            occurrence_counts[canonical] += 1
            fingerprint = hashlib.sha256(
                f"{canonical}\x1f{occurrence_counts[canonical]}".encode()
            ).hexdigest()
            if mapping.transaction_id:
                source_id = _required_text(raw[mapping.transaction_id], "transaction_id", 160)
                if source_id in identifiers:
                    raise ValueError("duplicate transaction identifier inside the file")
                identifiers[source_id] = canonical
                # 账户限定由持久化唯一索引提供；稳定来源 ID 不依赖导出顺序或日期范围。
                fingerprint = hashlib.sha256(f"source-id-v1:{source_id}".encode()).hexdigest()
            parsed_rows.append(
                ParsedStatementRow(
                    row_number=row_number,
                    booking_date=booking_date,
                    occurred_at=occurred_at,
                    merchant=merchant,
                    description=description,
                    amount=amount,
                    currency=currency,
                    fingerprint=fingerprint,
                    time_precision=(
                        "timestamp"
                        if re.search(r"[T ]\d{2}:\d{2}", raw[mapping.occurred_at])
                        else "date"
                    ),
                )
            )
        except ValueError as exc:
            errors.append(StatementRowError(row_number, "INVALID_ROW", str(exc)))

    return ParsedStatement(
        file_hash=file_hash,
        total_rows=len(raw_rows),
        rows=parsed_rows,
        errors=errors,
    )


def _parse_datetime(value: str | None) -> tuple[date, datetime]:
    """同时保留账务日期和绝对时间，避免时区换算改变银行侧入账日期。"""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("occurred_at is required")
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for pattern in ("%Y/%m/%d", "%d/%m/%Y", "%Y年%m月%d日"):
            try:
                parsed = datetime.strptime(raw, pattern)
                break
            except ValueError:
                continue
        else:
            raise ValueError("occurred_at must be an ISO or supported calendar date") from None
    booking_date = parsed.date()
    if parsed.tzinfo is None and re.search(r"[T ]\d{2}:\d{2}", raw):
        raise ValueError("Timestamp must include a timezone offset, for example +08:00")
    occurred_at = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return booking_date, occurred_at


def _parse_amount(value: str | None) -> Decimal:
    raw = (value or "").strip()
    # 通用格式只接受小数点；不猜测逗号是小数还是千位符，避免静默改变金额。
    if not re.fullmatch(r"[+-]?\d+(?:\.\d{1,2})?", raw):
        raise ValueError("amount must use a decimal point without grouping separators")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise ValueError("amount must be a decimal number") from None
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    if abs(amount) >= Decimal("10000000000000000"):
        raise ValueError("amount exceeds the supported range")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("amount must have at most two decimal places")
    return amount.quantize(Decimal("0.01"))


def _required_text(value: str | None, field: str, maximum: int) -> str:
    normalized = " ".join((value or "").split())
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _optional_text(value: str | None, maximum: int) -> str:
    normalized = " ".join((value or "").split())
    if len(normalized) > maximum:
        raise ValueError(f"description exceeds {maximum} characters")
    return normalized
