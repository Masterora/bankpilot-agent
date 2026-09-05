"""
文件职责：增加账单导入批次及交易来源指纹结构。

主要内容：创建 import_batches 表；为 transactions 增加账务日期、批次、源行和去重指纹字段。
关键边界：源文件正文不入库；账户内指纹唯一，已有交易使用空指纹保持兼容。

Revision ID: 20260904_0004
Revises: 20260904_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0004"
down_revision: str | None = "20260904_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建批次报告，并为交易建立可重复计算的来源索引。"""
    op.create_index(
        "uq_accounts_user_name_currency",
        "accounts",
        ["user_id", "name", "currency"],
        unique=True,
    )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("imported_rows", sa.Integer(), nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False),
        sa.Column("error_rows", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("field_mapping", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_batches_user_id", "import_batches", ["user_id"])
    op.create_index("ix_import_batches_account_id", "import_batches", ["account_id"])
    op.create_index("ix_import_batches_status", "import_batches", ["status"])
    op.create_index(
        "ix_import_batches_user_created", "import_batches", ["user_id", "created_at"]
    )
    op.add_column("transactions", sa.Column("import_batch_id", sa.Uuid(), nullable=True))
    op.add_column("transactions", sa.Column("booking_date", sa.Date(), nullable=True))
    # 旧数据只保留 UTC 时间，回填采用 UTC 日期，不依赖数据库会话时区。
    op.execute("UPDATE transactions SET booking_date = (occurred_at AT TIME ZONE 'UTC')::date")
    # 历史运行结果是独立快照，同步补齐字段，避免读取旧运行时领域契约校验失败。
    op.execute("""
        UPDATE runs SET result = jsonb_set(
            result::jsonb, '{transactions,items}',
            (SELECT jsonb_agg(
                CASE WHEN item ? 'booking_date' THEN item
                ELSE item || jsonb_build_object('booking_date',
                    ((item->>'occurred_at')::timestamptz AT TIME ZONE 'UTC')::date)
                END ORDER BY position)
             FROM jsonb_array_elements(result::jsonb #> '{transactions,items}')
                  WITH ORDINALITY AS entries(item, position))
        )::json
        WHERE jsonb_typeof(result::jsonb #> '{transactions,items}') = 'array'
          AND result::jsonb #> '{transactions,items}' <> '[]'::jsonb
    """)
    op.alter_column("transactions", "booking_date", nullable=False)
    op.add_column("transactions", sa.Column("source_row_number", sa.Integer(), nullable=True))
    op.add_column("transactions", sa.Column("source_fingerprint", sa.String(64), nullable=True))
    op.create_foreign_key(
        "fk_transactions_import_batch_id",
        "transactions",
        "import_batches",
        ["import_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_transactions_import_batch_id", "transactions", ["import_batch_id"])
    op.create_index(
        "ix_transactions_account_booking",
        "transactions",
        ["account_id", "booking_date"],
    )
    op.create_index(
        "uq_transactions_account_fingerprint",
        "transactions",
        ["account_id", "source_fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    """按依赖逆序移除导入批次与交易来源字段。"""
    op.drop_index("uq_transactions_account_fingerprint", table_name="transactions")
    op.drop_index("ix_transactions_account_booking", table_name="transactions")
    op.drop_index("ix_transactions_import_batch_id", table_name="transactions")
    op.drop_constraint(
        "fk_transactions_import_batch_id", "transactions", type_="foreignkey"
    )
    op.drop_column("transactions", "source_fingerprint")
    op.drop_column("transactions", "source_row_number")
    op.drop_column("transactions", "booking_date")
    op.drop_column("transactions", "import_batch_id")
    op.drop_table("import_batches")
    op.drop_index("uq_accounts_user_name_currency", table_name="accounts")
