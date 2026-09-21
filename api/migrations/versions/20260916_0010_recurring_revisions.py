"""
文件职责：增加按生效月份保存的周期配置修订。
主要内容：创建修订记录与关联约束，保留升级和回滚路径。
关键边界：后续配置追加生效，历史期次的预期不得被新配置覆盖。

Revision ID: 20260916_0010
Revises: 20260916_0009
Create Date: 2026-09-16 12:57:27.003033
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0010"
down_revision: str | Sequence[str] | None = "20260916_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recurring_revisions",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("effective_month", sa.Date(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("merchant", sa.String(length=160), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "cadence IN ('monthly', 'yearly')", name="ck_recurring_revision_cadence"
        ),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM effective_month) = 1", name="ck_recurring_revision_month"
        ),
        sa.CheckConstraint("amount > 0", name="ck_recurring_revision_amount"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["recurring_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "effective_month"),
    )


def downgrade() -> None:
    op.drop_table("recurring_revisions")
