"""
文件职责：增加助手预算提案与幂等回执存储。
主要内容：创建操作提案的归属、状态、期限和确认结果结构及回滚。
关键边界：提案不直接修改已有账本，确认写入仍由应用服务校验。

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
