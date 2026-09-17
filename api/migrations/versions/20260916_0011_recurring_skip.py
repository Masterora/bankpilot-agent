"""
文件职责：实现一次 Alembic 数据库结构变更。
变更摘要：记录用户确认的本期未发生，不修改账本金额
主要内容：`upgrade` 应用变更，`downgrade` 按相反顺序回滚变更。
关键边界：变更必须可审查，不在迁移中读取应用密钥或执行业务逻辑。

Revision ID: 20260916_0011
Revises: 20260916_0010
Create Date: 2026-09-16 14:00:55.542677
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0011"
down_revision: str | Sequence[str] | None = "20260916_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recurring_skips",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["recurring_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "due_date"),
    )


def downgrade() -> None:
    op.drop_table("recurring_skips")
