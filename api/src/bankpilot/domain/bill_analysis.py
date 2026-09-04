"""
文件职责：以确定性规则完成账单分类、金额统计与异常识别。

主要内容：
- `classify_transaction`：只对商户和备注做关键词匹配，并优先采用用户修正。
- `analyze_bill`：按币种和分类使用 Decimal 汇总收入、支出与净额。
- 异常规则：识别大额支出与短时间内可能重复的扣款，并返回可核验事实。

关键边界：本模块不调用模型；不同币种不合并；商户和备注始终按不可信数据处理。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from bankpilot.domain.contracts import (
    BillAnalysis,
    BillAnomaly,
    CategorySource,
    CategorySummary,
    CurrencySummary,
    TransactionCategory,
    TransactionItem,
)


@dataclass(frozen=True)
class Classification:
    category: TransactionCategory
    source: CategorySource
    rule_id: str


_CATEGORY_RULES: tuple[tuple[TransactionCategory, tuple[str, ...]], ...] = (
    (TransactionCategory.GROCERIES, ("超市", "生鲜", "grocery", "supermarket")),
    (TransactionCategory.DINING, ("餐厅", "咖啡", "外卖", "restaurant", "coffee")),
    (TransactionCategory.TRANSPORT, ("交通", "地铁", "公交", "打车", "taxi", "metro")),
    (TransactionCategory.SHOPPING, ("商城", "商店", "购物", "store", "shop")),
    (TransactionCategory.HOUSING, ("房租", "租金", "mortgage", "rent")),
    (TransactionCategory.UTILITIES, ("电费", "水费", "燃气", "话费", "utility")),
    (TransactionCategory.ENTERTAINMENT, ("影院", "游戏", "streaming", "cinema")),
    (TransactionCategory.HEALTHCARE, ("医院", "药房", "pharmacy", "clinic")),
    (TransactionCategory.EDUCATION, ("学费", "课程", "course", "tuition")),
    (TransactionCategory.TRAVEL, ("酒店", "航空", "hotel", "airline")),
    (TransactionCategory.TRANSFER, ("转账", "transfer")),
)

_LARGE_OUTFLOW_THRESHOLDS = {
    "CNY": Decimal("1000.00"),
    "USD": Decimal("150.00"),
    "EUR": Decimal("150.00"),
}


def classify_transaction(
    *,
    merchant: str,
    description: str,
    amount: Decimal,
    override: TransactionCategory | None = None,
) -> Classification:
    """返回稳定分类；商户文本仅参与普通字符串匹配，不能影响程序控制流。"""
    if override is not None:
        return Classification(override, CategorySource.USER, "category_user_override_v1")
    if amount > 0:
        return Classification(
            TransactionCategory.INCOME, CategorySource.RULE, "category_positive_amount_v1"
        )

    searchable = f"{merchant} {description}".casefold()
    for category, keywords in _CATEGORY_RULES:
        if any(keyword in searchable for keyword in keywords):
            return Classification(category, CategorySource.RULE, f"category_{category.value}_v1")
    return Classification(TransactionCategory.OTHER, CategorySource.RULE, "category_other_v1")


def analyze_bill(transactions: list[TransactionItem]) -> BillAnalysis:
    """使用原始 Decimal 金额计算账单汇总，并附加确定性异常事实。"""
    currency_totals: dict[str, dict[str, Decimal | int]] = defaultdict(
        lambda: {
            "income": Decimal("0.00"),
            "expense": Decimal("0.00"),
            "net": Decimal("0.00"),
            "count": 0,
        }
    )
    category_totals: dict[tuple[TransactionCategory, str], tuple[Decimal, int]] = {}

    for item in transactions:
        totals = currency_totals[item.currency]
        totals["net"] = Decimal(str(totals["net"])) + item.amount
        totals["count"] = int(totals["count"]) + 1
        if item.amount >= 0:
            totals["income"] = Decimal(str(totals["income"])) + item.amount
        else:
            totals["expense"] = Decimal(str(totals["expense"])) + abs(item.amount)

        category_key = (item.category, item.currency)
        current_amount, current_count = category_totals.get(
            category_key, (Decimal("0.00"), 0)
        )
        category_totals[category_key] = (current_amount + abs(item.amount), current_count + 1)

    currency_summaries = [
        CurrencySummary(
            currency=currency,
            income=Decimal(str(values["income"])),
            expense=Decimal(str(values["expense"])),
            net=Decimal(str(values["net"])),
            transaction_count=int(values["count"]),
        )
        for currency, values in sorted(currency_totals.items())
    ]
    category_summaries = [
        CategorySummary(
            category=category,
            currency=currency,
            amount=amount,
            transaction_count=count,
        )
        for (category, currency), (amount, count) in sorted(
            category_totals.items(), key=lambda entry: (entry[0][1], entry[0][0].value)
        )
    ]
    return BillAnalysis(
        currency_summaries=currency_summaries,
        category_summaries=category_summaries,
        anomalies=_detect_anomalies(transactions),
    )


def _detect_anomalies(transactions: list[TransactionItem]) -> list[BillAnomaly]:
    anomalies: list[BillAnomaly] = []
    for item in transactions:
        threshold = _LARGE_OUTFLOW_THRESHOLDS.get(item.currency)
        if item.amount < 0 and threshold is not None and abs(item.amount) >= threshold:
            anomalies.append(
                BillAnomaly(
                    rule_id="large_outflow_v1",
                    severity="warning",
                    transaction_ids=[item.id],
                    facts={
                        "amount": str(abs(item.amount)),
                        "currency": item.currency,
                        "threshold": str(threshold),
                    },
                )
            )

    duplicate_groups: dict[tuple[str, Decimal, str], list[TransactionItem]] = defaultdict(list)
    for item in transactions:
        if item.amount < 0:
            key = (item.merchant.casefold().strip(), item.amount, item.currency)
            duplicate_groups[key].append(item)
    for (_, amount, currency), group in duplicate_groups.items():
        ordered = sorted(group, key=lambda item: item.occurred_at)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current.occurred_at - previous.occurred_at <= timedelta(minutes=10):
                anomalies.append(
                    BillAnomaly(
                        rule_id="possible_duplicate_v1",
                        severity="notice",
                        transaction_ids=[previous.id, current.id],
                        facts={
                            "merchant": current.merchant,
                            "amount": str(abs(amount)),
                            "currency": currency,
                            "window_minutes": "10",
                        },
                    )
                )
    return anomalies
