"""
文件职责：增加周期期次未发生的确认记录。
主要内容：创建未发生记录、归属和唯一性约束，以及对应回滚。
关键边界：记录用户确认事实，不删除流水或改变账本金额。

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
