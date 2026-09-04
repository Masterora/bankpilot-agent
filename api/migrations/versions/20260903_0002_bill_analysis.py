"""
文件职责：创建账单分类修正的持久化结构。

主要内容：
- `upgrade`：创建交易分类修正表及用户查询索引。
- `downgrade`：删除分类修正表。

关键边界：修正记录与交易、用户同时绑定，删除原始数据时级联清理。

Revision ID: 20260903_0002
Revises: 20260901_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0002"
down_revision: str | None = "20260901_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建独立的用户分类修正表，不修改银行原始交易。"""
    op.create_table(
        "transaction_category_overrides",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("transaction_id"),
    )
    op.create_index(
        "ix_transaction_category_overrides_user_id",
        "transaction_category_overrides",
        ["user_id"],
    )


def downgrade() -> None:
    """删除分类修正结构。"""
    op.drop_table("transaction_category_overrides")
