"""Freeze recurring discovery creation proposals and confirmation receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20260929_0017"
down_revision = "20260929_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recurring_discovery_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("proposal_request_id", sa.Uuid(), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("group_key", sa.String(64), nullable=False),
        sa.Column("through", sa.Date(), nullable=False),
        sa.Column("discovery_snapshot_token", sa.String(64), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("merchant_normalization_version", sa.String(64), nullable=False),
        sa.Column("ledger_revision", sa.BigInteger(), nullable=False),
        sa.Column("evidence_digest", sa.String(64), nullable=False),
        sa.Column("account_name", sa.String(100), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=True),
        sa.UniqueConstraint("user_id", "proposal_request_id", name="uq_discovery_proposal_request"),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'expired')", name="ck_discovery_proposal_status"
        ),
    )
    op.create_index(
        "ix_discovery_proposals_user_group",
        "recurring_discovery_proposals",
        ["user_id", "group_key"],
    )
    op.create_index(
        "ix_discovery_proposals_user_status_expiry",
        "recurring_discovery_proposals",
        ["user_id", "status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discovery_proposals_user_status_expiry",
        table_name="recurring_discovery_proposals",
    )
    op.drop_index("ix_discovery_proposals_user_group", table_name="recurring_discovery_proposals")
    op.drop_table("recurring_discovery_proposals")
