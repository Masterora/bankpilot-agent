"""
文件职责：实现一次 Alembic 数据库结构变更。
变更摘要：月度预算、手动周期项与逐期流水关联
主要内容：`upgrade` 应用变更，`downgrade` 按相反顺序回滚变更。
关键边界：变更必须可审查，不在迁移中读取应用密钥或执行业务逻辑。

Revision ID: 20260916_0009
Revises: 20260915_0008
Create Date: 2026-09-16 11:56:12.513290
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0009"
down_revision: str | Sequence[str] | None = "20260915_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("EXTRACT(DAY FROM month) = 1", name="ck_budgets_month"),
        sa.CheckConstraint("amount > 0", name="ck_budgets_amount"),
        sa.CheckConstraint("version > 0", name="ck_budgets_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "month", "category", "currency"),
        sa.UniqueConstraint("id"),
    )
    op.create_table(
        "recurring_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("merchant", sa.String(length=160), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("cadence IN ('monthly', 'yearly')", name="ck_recurring_cadence"),
        sa.CheckConstraint("status IN ('active', 'paused', 'ended')", name="ck_recurring_status"),
        sa.CheckConstraint("amount > 0", name="ck_recurring_amount"),
        sa.CheckConstraint("version > 0", name="ck_recurring_version"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_recurring_plans_user_id"), "recurring_plans", ["user_id"], unique=False
    )
    op.create_table(
        "recurring_matches",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["recurring_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "due_date"),
        sa.UniqueConstraint("transaction_id"),
    )


def downgrade() -> None:
    op.drop_table("recurring_matches")
    op.drop_index(op.f("ix_recurring_plans_user_id"), table_name="recurring_plans")
    op.drop_table("recurring_plans")
    op.drop_table("budgets")
