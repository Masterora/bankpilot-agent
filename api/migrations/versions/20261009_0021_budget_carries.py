"""Explicit monthly budget carryover receipts.

Revision ID: 20261009_0021
Revises: 20261008_0020
"""

import sqlalchemy as sa
from alembic import op

revision = "20261009_0021"
down_revision = "20261008_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_carries",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "month"),
        sa.UniqueConstraint("user_id", "operation_id", name="uq_budget_carry_operation"),
        sa.CheckConstraint("EXTRACT(DAY FROM month) = 1", name="ck_budget_carry_month"),
    )


def downgrade() -> None:
    # Budget amounts remain; only carryover recovery receipts are removed.
    op.drop_table("budget_carries")
