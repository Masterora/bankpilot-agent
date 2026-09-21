"""
文件职责：为助手会话与轮次增加独立搜索上下文。
主要内容：保存版本化搜索条件与受理时上下文，并提供对应回滚。
关键边界：搜索上下文与消费范围独立；不根据历史文本补造搜索事实。
"""
import sqlalchemy as sa
from alembic import op

revision = "20260921_0014"
down_revision = "20260921_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assistant_conversations", sa.Column("search_context", sa.JSON(), nullable=True))
    op.add_column(
        "assistant_conversations",
        sa.Column("context_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("assistant_turns", sa.Column("search_context", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("assistant_turns", "search_context")
    op.drop_column("assistant_conversations", "context_version")
    op.drop_column("assistant_conversations", "search_context")
