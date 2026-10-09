"""Persist opt-in conversation search subscriptions.

Revision ID: 20261008_0020
Revises: 20260930_0019
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0020"
down_revision = "20260930_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("search_subscribed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("search_fingerprint", sa.String(64), nullable=True),
        sa.Column("search_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_check_error", sa.String(80), nullable=True),
        sa.Column("search_subscription_epoch", sa.String(64), nullable=True),
    ):
        op.add_column("assistant_conversations", column)
    op.create_index(
        "ix_assistant_search_subscription",
        "assistant_conversations",
        ["search_subscribed", "search_checked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_search_subscription", "assistant_conversations")
    for column in (
        "search_subscription_epoch",
        "search_check_error",
        "search_changed_at",
        "search_checked_at",
        "search_fingerprint",
        "search_subscribed",
    ):
        op.drop_column("assistant_conversations", column)
