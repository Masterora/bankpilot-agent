"""
文件职责：验证自动字段识别的确定性边界。
主要内容：分隔符与 BOM、歧义字段、独立收支方向拒绝。
关键边界：测试内容为人工构造的格式用例，不作为银行来源验收样本。
"""

import pytest

from bankpilot.domain.source_detection import detect_mapping


def test_detects_delimiter_and_preserves_source_headers() -> None:
    mapping = detect_mapping("\ufeff日期;商户;金额\n2026-09-01;Store;-5.00\n")
    assert mapping.occurred_at == "日期"
    assert mapping.merchant == "商户"
    assert mapping.description is None


@pytest.mark.parametrize(
    "content",
    [
        "date,日期,merchant,amount\n2026-09-01,2026-09-01,Store,-5\n",
        "日期,商户,金额,收/支\n2026-09-01,Store,5,支出\n",
        "日期,商户,金额,交易状态\n2026-09-01,Store,-5,失败\n",
        "银行交易证明\n日期,商户,金额\n2026-09-01,Store,-5\n",
    ],
)
def test_uncertain_formats_are_not_guessed(content: str) -> None:
    with pytest.raises(ValueError):
        detect_mapping(content)
