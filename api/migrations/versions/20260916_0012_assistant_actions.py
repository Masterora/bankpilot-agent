"""助手预算操作提案与幂等回执；不修改既有账本。

Revision ID: 20260916_0012
Revises: 20260916_0011
"""

import sqlalchemy as sa
from alembic import op

revision = "20260916_0012"
down_revision = "20260916_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("before_amount", sa.String(32)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'applied', 'cancelled')", name="ck_assistant_action_status"
        ),
    )
    op.create_index("ix_assistant_actions_user_id", "assistant_actions", ["user_id"])


def downgrade() -> None:
    op.drop_table("assistant_actions")
