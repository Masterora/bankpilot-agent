"""
文件职责：保存时间精度与用户核查结论。
主要内容：交易时间精度字段、按用户隔离的异常核查表。
关键边界：已有时间精度未知，禁止根据补零时间回填为精确时间；不改变源交易。
"""

import sqlalchemy as sa
from alembic import op

revision = "20260905_0005"
down_revision = "20260904_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加证据精度及持久化核查状态。"""
    op.add_column(
        "transactions",
        sa.Column("time_precision", sa.String(16), server_default="unknown", nullable=False),
    )
    op.create_table(
        "review_decisions",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    """移除核查结论和精度字段，不删除原交易。"""
    op.drop_table("review_decisions")
    op.drop_column("transactions", "time_precision")
