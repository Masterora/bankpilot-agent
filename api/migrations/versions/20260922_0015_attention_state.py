"""Add persistent attention state, preferences, and idempotent operation receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20260922_0015"
down_revision = "20260921_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attention_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_date", sa.Date(), nullable=False),
        sa.Column("attention_type", sa.String(40), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("fact_signature", sa.String(64), nullable=False),
        sa.Column("fact_status", sa.String(16), nullable=False),
        sa.Column("unknown_reason", sa.String(80)),
        sa.Column("unknown_since", sa.DateTime(timezone=True)),
        sa.Column("last_tracking_gap", sa.JSON()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("state_attention_type", sa.String(40)),
        sa.Column("snoozed_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "user_id", "source_type", "source_id", "source_date", name="uq_attention_source"
        ),
        sa.CheckConstraint("generation > 0 AND revision > 0", name="ck_attention_versions"),
        sa.CheckConstraint(
            "source_type IN ('budget', 'recurring')", name="ck_attention_source_type"
        ),
        sa.CheckConstraint(
            "fact_status IN ('active', 'inactive', 'unknown')", name="ck_attention_fact_status"
        ),
        sa.CheckConstraint("state IN ('unread', 'read', 'snoozed')", name="ck_attention_state"),
        sa.CheckConstraint(
            "(state = 'snoozed') = (snoozed_until IS NOT NULL)", name="ck_attention_snoozed_until"
        ),
        sa.CheckConstraint(
            "(fact_status = 'unknown') = "
            "(unknown_reason IS NOT NULL AND unknown_since IS NOT NULL)",
            name="ck_attention_unknown",
        ),
    )
    op.create_index("ix_attention_user_date", "attention_states", ["user_id", "source_date"])
    op.create_table(
        "attention_preferences",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("attention_type", sa.String(40), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version > 0", name="ck_attention_preference_version"),
    )
    op.create_table(
        "attention_operations",
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
    op.drop_table("attention_operations")
    op.drop_table("attention_preferences")
    op.drop_index("ix_attention_user_date", table_name="attention_states")
    op.drop_table("attention_states")
