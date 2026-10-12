"""Account month declarations and recurring status boundaries."""

import sqlalchemy as sa
from alembic import op

revision = "20261009_0022"
down_revision = "20261009_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recurring_plans", sa.Column("status_known_from", sa.Date(), nullable=True))
    op.create_table(
        "recurring_status_changes",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["recurring_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "effective_date"),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'ended')", name="ck_recurring_change_status"
        ),
    )
    op.create_table(
        "account_month_reviews",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("ledger_revision", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id", "month"),
        sa.CheckConstraint(
            "status IN ('reviewed', 'closed', 'open')", name="ck_month_review_status"
        ),
        sa.CheckConstraint("EXTRACT(DAY FROM month) = 1", name="ck_month_review_month"),
        sa.CheckConstraint("version > 0 AND ledger_revision >= 0", name="ck_month_review_version"),
    )
    op.create_index("ix_account_month_reviews_user_id", "account_month_reviews", ["user_id"])


def downgrade() -> None:
    op.drop_table("account_month_reviews")
    op.drop_table("recurring_status_changes")
    op.drop_column("recurring_plans", "status_known_from")
