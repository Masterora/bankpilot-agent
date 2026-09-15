"""
文件职责：增加账本修订号与持久月报任务结构。

主要内容：为用户增加修订号，并创建月报状态、租约、快照和幂等约束。

关键边界：既有账本从修订号零开始，不伪造历史版本，降级必须完整移除新增结构。
"""

import sqlalchemy as sa
from alembic import op

revision = "20260911_0007"
down_revision = "20260906_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("ledger_revision", sa.BigInteger(), nullable=False, server_default="0")
    )
    op.create_table(
        "monthly_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ledger_revision", sa.BigInteger(), nullable=True),
        sa.Column("rule_version", sa.String(64), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'DELETED')",
            name="ck_monthly_reports_status",
        ),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 3", name="ck_monthly_reports_attempts"),
    )
    op.create_index(
        "uq_monthly_reports_idempotency",
        "monthly_reports",
        ["user_id", "idempotency_key"],
        unique=True,
    )
    op.create_index("ix_monthly_reports_user_created", "monthly_reports", ["user_id", "created_at"])
    op.create_index(
        "ix_monthly_reports_queue", "monthly_reports", ["status", "available_at", "lease_until"]
    )


def downgrade() -> None:
    op.drop_table("monthly_reports")
    op.drop_column("users", "ledger_revision")
