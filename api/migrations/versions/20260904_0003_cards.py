"""
文件职责：创建卡片清单的持久化结构。

主要内容：
- `upgrade`：创建 cards 表、账户时间索引和状态约束。
- `downgrade`：删除 cards 表。

关键边界：卡片通过账户继承用户归属；仅保存展示名和尾号，不保存完整卡号。

Revision ID: 20260904_0003
Revises: 20260903_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0003"
down_revision: str | None = "20260903_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建卡片表，并限制可展示字段和状态集合。"""
    op.create_table(
        "cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("last_four", sa.String(length=4), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(last_four) = 4", name="ck_cards_last_four_length"),
        sa.CheckConstraint("status IN ('ACTIVE', 'LOCKED')", name="ck_cards_status"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cards_account_created", "cards", ["account_id", "created_at"])


def downgrade() -> None:
    """删除卡片清单结构。"""
    op.drop_table("cards")
