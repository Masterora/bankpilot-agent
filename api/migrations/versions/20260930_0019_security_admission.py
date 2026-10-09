"""Add shared security admission counters and expiring reservations.

Revision ID: 20260930_0019
Revises: 20260929_0018
"""
import sqlalchemy as sa
from alembic import op

revision = "20260930_0019"
down_revision = "20260929_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_budgets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("used", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("used >= 0", name="ck_security_budget_used"),
    )
    op.create_index("ix_security_budgets_expiry", "security_budgets", ["expires_at"])
    op.create_table(
        "security_leases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(64), nullable=False),
        sa.Column("configuration", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_security_leases_purpose", "security_leases", ["purpose", "subject", "expires_at"]
    )
    op.create_index("ix_security_leases_expiry", "security_leases", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_security_leases_expiry", "security_leases")
    op.drop_index("ix_security_leases_purpose", "security_leases")
    op.drop_table("security_leases")
    op.drop_index("ix_security_budgets_expiry", "security_budgets")
    op.drop_table("security_budgets")
