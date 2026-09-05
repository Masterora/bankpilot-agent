"""
文件职责：识别个人支付账单结构，将来源语义转换为标准流水。
主要内容：支付宝与微信独立字段配置、表头定位、状态/方向校验、来源编号隔离。
关键边界：只处理明确结构；不推断中性交易方向或退款抵销；每个排除行可追溯。
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class SourceProfile:
    key: str
    label: str
    time: str
    merchant: str
    amount: str
    identifier: str
    description: str
    status: str
    signature: frozenset[str]
    successful: frozenset[str]


PROFILES = (
    SourceProfile(
        "wechat",
        "微信",
        "交易时间",
        "交易对方",
        "金额(元)",
        "交易单号",
        "商品",
        "当前状态",
        frozenset({"交易类型", "支付方式", "商户单号", "收/支"}),
        frozenset({"支付成功", "已收钱", "已转账", "已存入", "已到账", "退款成功"}),
    ),
    SourceProfile(
        "alipay",
        "支付宝",
        "交易时间",
        "交易对方",
        "金额",
        "交易订单号",
        "商品说明",
        "交易状态",
        frozenset({"交易分类", "对方账号", "收/支"}),
        frozenset({"交易成功", "支付成功", "退款成功"}),
    ),
    SourceProfile(
        "alipay",
        "支付宝",
        "交易创建时间",
        "交易对方",
        "金额(元)",
        "交易号",
        "商品名称",
        "交易状态",
        frozenset({"商家订单号", "收/支", "资金状态"}),
        frozenset({"交易成功", "支付成功", "交易完成", "退款成功"}),
    ),
)


@dataclass(frozen=True)
class SourceTable:
    profile: SourceProfile
    headers: list[str]
    rows: list[tuple[int, list[str]]]


def clean_header(value: str) -> str:
    return value.strip().replace("（", "(").replace("）", ")")


def locate_source(content: str) -> SourceTable | None:
    """通过字段组合定位表头；说明行不写入账本，不依赖文件名或固定行数。"""
    if "收/支" not in content or not any(s in content for s in ("当前状态", "交易状态")):
        return None
    reader = csv.reader(io.StringIO(content.removeprefix("\ufeff")), strict=True)
    rows: list[tuple[int, list[str]]] = []
    for row in reader:
        rows.append((reader.line_num, row))
        if len(rows) > 5200:
            raise ValueError("Statement exceeds the row limit")
    found: list[tuple[int, SourceProfile, list[str]]] = []
    for index, (_, row) in enumerate(rows[:100]):
        headers = [clean_header(v) for v in row]
        for profile in PROFILES:
            required = profile.signature | {
                profile.time,
                profile.merchant,
                profile.amount,
                profile.identifier,
                profile.description,
                profile.status,
            }
            if required.issubset(headers):
                if len(set(headers)) != len(headers):
                    raise ValueError("Duplicate source columns")
                found.append((index, profile, headers))
    if not found:
        return None
    if len(found) != 1:
        raise ValueError("Multiple statement headers are not supported")
    index, profile, headers = found[0]
    return SourceTable(profile, headers, rows[index + 1 :])


def source_account(content: str, account_name: str) -> str:
    """账户以来源限定命名空间，避免两个平台的相同用户标签混为同一账户。"""
    try:
        table = locate_source(content)
    except csv.Error as exc:
        raise ValueError("CSV structure is invalid") from exc
    if table is None:
        return account_name
    prefix = table.profile.label + " · "
    value = account_name if account_name.startswith(prefix) else prefix + account_name
    if len(value) > 100:
        raise ValueError("Account label is too long")
    return value


def normalize_row(profile: SourceProfile, row: dict[str, str]) -> list[str] | None:
    """返回标准字段；明确未成功/中性记录返回排除，不把退款状态合成为入账。"""
    state, direction = row[profile.status].strip(), row["收/支"].strip()
    if state in {"交易关闭", "已关闭", "支付失败", "已撤销", "未支付"}:
        return None
    if direction in {"/", "不计收支", "不计收入支出"}:
        return None
    if state not in profile.successful:
        raise ValueError(f"状态待适配：{state}；未写入，请保留原文件")
    if direction not in {"收入", "支出"}:
        raise ValueError("收支方向无法确定")
    if "退款" in state and direction != "收入":
        raise ValueError("退款状态不能确定独立退款金额与日期")
    for key in ("成功退款(元)", "退款金额"):
        if row.get(key, "").strip() not in {"", "0", "0.00", "/"}:
            raise ValueError("含退款汇总，不能将原订单静默视为独立资金流水")
    raw = row[profile.amount].strip().lstrip("¥￥").strip()
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw):
        raise ValueError("来源金额必须为无分组符的非负数")
    amount = Decimal(raw) * (-1 if direction == "支出" else 1)
    timestamp = row[profile.time].strip()
    parsed_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    identifier = row[profile.identifier].strip().lstrip("'`").strip()
    if not identifier or identifier == "/":
        raise ValueError("缺少稳定交易编号")
    merchant = row[profile.merchant].strip()
    if not merchant or merchant == "/":
        raise ValueError("缺少交易对方")
    description = row[profile.description].strip()
    remark = row.get("备注", "").strip()
    return [
        parsed_time.isoformat() + "+08:00",
        merchant,
        format(amount, ".2f"),
        " / ".join(x for x in [description, remark] if x and x != "/"),
        profile.key + ":" + identifier,
    ]
