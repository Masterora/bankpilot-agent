"""Persist assistant conversations and fenced turns.

Revision ID: 20260921_0013
Revises: 20260916_0012
"""

import sqlalchemy as sa
from alembic import op

revision = "20260921_0013"
down_revision = "20260916_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("creation_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(80)),
        sa.Column("scope", sa.JSON()),
        sa.Column("month", sa.Date()),
        *[
            sa.Column(
                name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            )
            for name in ("created_at", "updated_at", "accessed_at")
        ],
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("user_id", "creation_id", name="uq_assistant_creation"),
    )
    op.create_index("ix_assistant_conversations_user_id", "assistant_conversations", ["user_id"])
    op.add_column("assistant_actions", sa.Column("conversation_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_action_conversation",
        "assistant_actions",
        "assistant_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_assistant_actions_conversation_id", "assistant_actions", ["conversation_id"]
    )
    op.execute("UPDATE assistant_actions SET status='cancelled' WHERE status='pending'")
    op.create_table(
        "assistant_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("scope", sa.JSON()),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("retry_of", sa.Uuid()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("completion_token", sa.Uuid(), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("result_version", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("action_id", sa.Uuid(), sa.ForeignKey("assistant_actions.id")),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_assistant_request"),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_assistant_sequence"),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')", name="ck_assistant_turn_status"
        ),
    )
    op.create_index("ix_assistant_turns_conversation_id", "assistant_turns", ["conversation_id"])
    op.create_index("ix_assistant_turns_deadline", "assistant_turns", ["deadline"])
    op.create_index(
        "uq_assistant_processing",
        "assistant_turns",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'processing'"),
    )


def downgrade() -> None:
    op.drop_table("assistant_turns")
    op.drop_column("assistant_actions", "conversation_id")
    op.drop_table("assistant_conversations")
