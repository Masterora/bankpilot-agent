"""
文件职责：实现一次 Alembic 数据库结构变更。
变更摘要：Feishu bindings inbox and Alipay sandbox orders
主要内容：`upgrade` 应用变更，`downgrade` 按相反顺序回滚变更。
关键边界：变更必须可审查，不在迁移中读取应用密钥或执行业务逻辑。

Revision ID: 20261016_0024
Revises: 20261013_0023
Create Date: 2026-10-16 11:29:17.005896
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_0024"
down_revision: str | Sequence[str] | None = "20261013_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alipay_sandbox_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("seller_id", sa.String(length=128), nullable=False),
        sa.Column("subject", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trade_no", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('WAIT_BUYER_PAY', 'TRADE_SUCCESS', 'TRADE_FINISHED', 'TRADE_CLOSED')",
            name="ck_alipay_order_status",
        ),
        sa.CheckConstraint("amount > 0 AND amount <= 10000", name="ck_alipay_sandbox_amount"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_no"),
        sa.UniqueConstraint("user_id", "operation_id", name="uq_alipay_order_operation"),
    )
    op.create_index(
        op.f("ix_alipay_sandbox_orders_user_id"), "alipay_sandbox_orders", ["user_id"], unique=False
    )
    op.create_table(
        "feishu_bindings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("open_id", sa.String(length=128), nullable=True),
        sa.Column("generation", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_key", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("code_hash"),
        sa.UniqueConstraint("open_id"),
    )
    op.create_table(
        "feishu_messages",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("binding_generation", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'sent', 'failed', 'cancelled')",
            name="ck_feishu_message_status",
        ),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 3", name="ck_feishu_message_attempts"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index(
        "ix_feishu_messages_queue", "feishu_messages", ["status", "lease_until"], unique=False
    )
    op.create_index(
        op.f("ix_feishu_messages_user_id"), "feishu_messages", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_feishu_messages_user_id"), table_name="feishu_messages")
    op.drop_index("ix_feishu_messages_queue", table_name="feishu_messages")
    op.drop_table("feishu_messages")
    op.drop_table("feishu_bindings")
    op.drop_index(op.f("ix_alipay_sandbox_orders_user_id"), table_name="alipay_sandbox_orders")
    op.drop_table("alipay_sandbox_orders")
