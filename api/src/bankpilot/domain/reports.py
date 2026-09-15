"""
文件职责：定义月报领域契约。

主要内容：包含报告状态、月份范围、规则版本和确定性快照构建。

关键边界：报告计算复用账单分析规则，不依赖模型、HTTP 或数据库。
"""

import calendar
from datetime import date
from enum import StrEnum

from bankpilot.domain.bill_analysis import analyze_bill
from bankpilot.domain.contracts import BillAnalysis, ReviewSnapshot

REPORT_RULE_VERSION = "monthly_report_v1"


class ReportStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DELETED = "DELETED"


def month_period(month: date) -> tuple[date, date]:
    return month.replace(day=1), month.replace(day=calendar.monthrange(month.year, month.month)[1])


class MonthlySnapshot(ReviewSnapshot):
    month: date
    report_rule_version: str
    analysis: BillAnalysis


def build_report(month: date, snapshot: ReviewSnapshot) -> MonthlySnapshot:
    start, end = month_period(month)
    if (snapshot.transactions.start_date, snapshot.transactions.end_date) != (start, end):
        raise ValueError("Report evidence does not match the requested month")
    return MonthlySnapshot(
        **snapshot.model_dump(),
        month=start,
        report_rule_version=REPORT_RULE_VERSION,
        analysis=analyze_bill(snapshot.transactions.items),
    )
