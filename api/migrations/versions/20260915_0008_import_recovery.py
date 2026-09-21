"""
文件职责：增加可恢复导入的操作身份与统计字段。
主要内容：升级和回滚导入批次的请求摘要、幂等信息及分类计数结构。
关键边界：历史批次不伪造新统计口径；迁移不读取或保存账单原文件。
"""
import sqlalchemy as sa
from alembic import op

revision = "20260915_0008"
down_revision = "20260911_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, kind in (
        ("idempotency_key", sa.Uuid()),
        ("request_digest", sa.String(64)),
        ("parser_version", sa.String(64)),
        ("new_rows", sa.Integer()),
        ("skipped_rows", sa.Integer()),
        ("issue_count", sa.Integer()),
    ):
        op.add_column("import_batches", sa.Column(name, kind, nullable=True))
    op.create_index(
        "uq_import_batches_user_key", "import_batches", ["user_id", "idempotency_key"], unique=True
    )
    op.create_check_constraint(
        "ck_import_key_digest",
        "import_batches",
        "(idempotency_key IS NULL) = (request_digest IS NULL)",
    )
    op.create_check_constraint(
        "ck_import_counts",
        "import_batches",
        "idempotency_key IS NULL OR (parser_version IS NOT NULL "
        "AND new_rows IS NOT NULL AND skipped_rows IS NOT NULL AND issue_count IS NOT NULL "
        "AND new_rows >= 0 AND skipped_rows >= 0 AND issue_count >= error_rows "
        "AND error_rows >= 0 AND duplicate_rows >= 0 AND imported_rows >= 0 "
        "AND total_rows = new_rows + duplicate_rows + skipped_rows + error_rows "
        "AND (status = 'REVOKED' OR (status = 'REJECTED' AND imported_rows = 0) "
        "OR (status IN ('COMPLETED', 'COMPLETED_WITH_DUPLICATES') "
        "AND imported_rows = new_rows AND error_rows = 0)))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_import_counts", "import_batches")
    op.drop_constraint("ck_import_key_digest", "import_batches")
    op.drop_index("uq_import_batches_user_key", "import_batches")
    for name in (
        "issue_count",
        "skipped_rows",
        "new_rows",
        "parser_version",
        "request_digest",
        "idempotency_key",
    ):
        op.drop_column("import_batches", name)
