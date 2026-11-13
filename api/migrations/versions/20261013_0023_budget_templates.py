"""Reusable budget limits and immutable application receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20261013_0023"
down_revision = "20261009_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_templates",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "id"),
        sa.CheckConstraint("version > 0", name="ck_budget_template_version"),
    )
    op.create_table(
        "budget_template_applications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "operation_id"),
    )


def downgrade() -> None:
    op.drop_table("budget_template_applications")
    op.drop_table("budget_templates")
