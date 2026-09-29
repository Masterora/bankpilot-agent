"""Persist user decisions and frozen operation receipts for recurring discovery."""

import sqlalchemy as sa
from alembic import op

revision = "20260929_0016"
down_revision = "20260922_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recurring_discovery_decisions",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("group_key", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("normalized_merchant", sa.Text(), nullable=False),
        sa.Column("merchant_normalization_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("target_plan_id", sa.Uuid()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'ignored', 'linked', 'created')",
            name="ck_discovery_decision_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_discovery_decision_version"),
        sa.CheckConstraint(
            "(status IN ('linked', 'created')) = (target_plan_id IS NOT NULL)",
            name="ck_discovery_decision_target",
        ),
    )
    op.create_index(
        "ix_discovery_decisions_user_status",
        "recurring_discovery_decisions",
        ["user_id", "status", "updated_at"],
    )
    op.create_table(
        "recurring_discovery_operations",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("operation_id", sa.Uuid(), primary_key=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("recurring_discovery_operations")
    op.drop_index("ix_discovery_decisions_user_status", table_name="recurring_discovery_decisions")
    op.drop_table("recurring_discovery_decisions")
