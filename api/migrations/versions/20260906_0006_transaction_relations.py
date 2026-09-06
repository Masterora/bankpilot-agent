"""
文件职责：增加稳定账户来源和独立交易关系存储。
主要内容：从导入报告回填明确来源；关系外键、状态约束、索引与并发版本。
关键边界：仅使用报告中的来源事实；删除源交易自动清除关联，不修改原始金额。
"""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0006"
down_revision = "20260905_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """扩展账户属性与交易关系，不回填未经确认的关联。"""
    op.add_column(
        "accounts", sa.Column("source", sa.String(16), nullable=False, server_default="standard")
    )
    op.execute("""
        UPDATE accounts SET source = sources.source FROM (
          SELECT account_id, min(split_part(field_mapping->>'source', ':', 1)) AS source
          FROM import_batches WHERE account_id IS NOT NULL
          GROUP BY account_id
          HAVING count(DISTINCT split_part(field_mapping->>'source', ':', 1)) = 1
        ) sources WHERE accounts.id = sources.account_id
          AND sources.source IN ('wechat', 'alipay')
    """)
    op.create_table(
        "transaction_relations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "first_id",
            sa.Uuid(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "second_id",
            sa.Uuid(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("first_id <> second_id", name="ck_relations_distinct"),
        sa.CheckConstraint("kind IN ('duplicate', 'transfer', 'refund')", name="ck_relations_kind"),
        sa.CheckConstraint(
            "state IN ('confirmed', 'rejected', 'revoked')", name="ck_relations_state"
        ),
    )
    for column in ("user_id", "first_id", "second_id"):
        op.create_index(f"ix_transaction_relations_{column}", "transaction_relations", [column])
    op.create_index(
        "uq_relations_pair",
        "transaction_relations",
        ["user_id", "kind", "first_id", "second_id"],
        unique=True,
    )


def downgrade() -> None:
    """移除关联与来源属性，保留交易及导入报告。"""
    op.drop_table("transaction_relations")
    op.drop_column("accounts", "source")
