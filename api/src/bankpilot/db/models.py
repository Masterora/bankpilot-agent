"""
文件职责：定义 BankPilot 身份、账户、卡片、账单导入、账务分析与 Agent 运行的 ORM 模型。

主要内容：
- 身份与账务：`UserRecord`、`SessionRecord`、`AccountRecord`、`CardRecord`、`TransactionRecord`。
- 账单导入：`ImportBatchRecord` 保存来源、映射、统计和失败行报告。
- 分析修正：`TransactionCategoryOverrideRecord` 保存用户确认的交易分类。
- 交易关系：`TransactionRelationRecord` 保存双边证据、确认状态及版本，原交易不改写。
- Agent 运行：`RunRecord` 保存状态、计划、结果、错误和模型信息。
- 审计记录：`AuditEventRecord` 按运行保存有序事件。

关键边界：所有业务归属通过外键表达；复合索引服务于归属和时间范围查询。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bankpilot.db.base import Base
from bankpilot.domain.contracts import CardStatus, RunStatus
from bankpilot.domain.reports import ReportStatus


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    ledger_revision: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    accounts: Mapped[list["AccountRecord"]] = relationship(cascade="all, delete-orphan")


class MonthlyReportRecord(Base):
    """持久任务与一次生成结果；删除保留幂等墓碑，但清除所有快照证据。"""

    __tablename__ = "monthly_reports"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    month: Mapped[date] = mapped_column(Date)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), default=ReportStatus.QUEUED)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claim_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ledger_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rule_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("uq_monthly_reports_idempotency", "user_id", "idempotency_key", unique=True),
        Index("ix_monthly_reports_user_created", "user_id", "created_at"),
        Index("ix_monthly_reports_queue", "status", "available_at", "lease_until"),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'DELETED')",
            name="ck_monthly_reports_status",
        ),
        CheckConstraint("attempts >= 0 AND attempts <= 3", name="ck_monthly_reports_attempts"),
    )


class SessionRecord(Base):
    """仅通过单向令牌哈希标识的可过期登录会话。"""

    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountRecord(Base):
    __tablename__ = "accounts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    source: Mapped[str] = mapped_column(String(16), default="standard", server_default="standard")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transactions: Mapped[list["TransactionRecord"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    cards: Mapped[list["CardRecord"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("uq_accounts_user_name_currency", "user_id", "name", "currency", unique=True),
    )


class CardRecord(Base):
    """保存本地银行适配器可识别的卡片，以及后续操作所需的稳定标识。"""

    __tablename__ = "cards"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    display_name: Mapped[str] = mapped_column(String(100))
    last_four: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(16), default=CardStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    account: Mapped[AccountRecord] = relationship(back_populates="cards")

    __table_args__ = (
        CheckConstraint("length(last_four) = 4", name="ck_cards_last_four_length"),
        CheckConstraint("status IN ('ACTIVE', 'LOCKED')", name="ck_cards_status"),
        Index("ix_cards_account_created", "account_id", "created_at"),
    )


class TransactionRecord(Base):
    __tablename__ = "transactions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    booking_date: Mapped[date] = mapped_column(Date)
    time_precision: Mapped[str] = mapped_column(
        String(16), default="unknown", server_default="unknown"
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    merchant: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(500), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    import_batch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    account: Mapped[AccountRecord] = relationship(back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_account_occurred", "account_id", "occurred_at"),
        Index("ix_transactions_account_booking", "account_id", "booking_date"),
        Index(
            "uq_transactions_account_fingerprint",
            "account_id",
            "source_fingerprint",
            unique=True,
        ),
    )


class ImportBatchRecord(Base):
    """保存一次导入的可追溯结果；源文件正文不进入数据库。"""

    __tablename__ = "import_batches"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account_name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3))
    file_name: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    field_mapping: Mapped[dict[str, str | None]] = mapped_column(JSON)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_import_batches_user_created", "user_id", "created_at"),
        Index("uq_import_batches_user_key", "user_id", "idempotency_key", unique=True),
        CheckConstraint(
            "(idempotency_key IS NULL) = (request_digest IS NULL)",
            name="ck_import_key_digest",
        ),
        CheckConstraint(
            "idempotency_key IS NULL OR (parser_version IS NOT NULL "
            "AND new_rows IS NOT NULL AND skipped_rows IS NOT NULL AND issue_count IS NOT NULL "
            "AND new_rows >= 0 AND skipped_rows >= 0 AND issue_count >= error_rows "
            "AND error_rows >= 0 AND duplicate_rows >= 0 AND imported_rows >= 0 "
            "AND total_rows = new_rows + duplicate_rows + skipped_rows + error_rows "
            "AND (status = 'REVOKED' OR (status = 'REJECTED' AND imported_rows = 0) "
            "OR (status IN ('COMPLETED', 'COMPLETED_WITH_DUPLICATES') "
            "AND imported_rows = new_rows AND error_rows = 0)))",
            name="ck_import_counts",
        ),
    )


class TransactionCategoryOverrideRecord(Base):
    """独立保存用户分类修正，避免覆盖银行侧原始交易数据。"""

    __tablename__ = "transaction_category_overrides"

    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReviewDecisionRecord(Base):
    """保存用户对规则证据的判断；判断不修改金额，也不替代银行确认。"""

    __tablename__ = "review_decisions"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(500))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TransactionRelationRecord(Base):
    """独立关联两条流水；删除任一源交易时清除关联，避免残留抵销。"""

    __tablename__ = "transaction_relations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    first_id: Mapped[UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    second_id: Mapped[UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("first_id <> second_id", name="ck_relations_distinct"),
        CheckConstraint("kind IN ('duplicate', 'transfer', 'refund')", name="ck_relations_kind"),
        CheckConstraint("state IN ('confirmed', 'rejected', 'revoked')", name="ck_relations_state"),
        Index("uq_relations_pair", "user_id", "kind", "first_id", "second_id", unique=True),
    )


class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.CREATED.value, index=True)
    draft_action: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model_info: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditEventRecord(Base):
    """按运行记录归档的只追加事件，用于解释流程进度与失败。"""

    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int]
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("uq_audit_run_sequence", "run_id", "sequence", unique=True),)


class BudgetRecord(Base):
    """按月、分类和币种保存预算；实际支出从当前账本计算，不保存重复统计。"""

    __tablename__ = "budgets"
    id: Mapped[UUID] = mapped_column(Uuid, default=uuid4, unique=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_budgets_amount"),
        CheckConstraint("version > 0", name="ck_budgets_version"),
        CheckConstraint("EXTRACT(DAY FROM month) = 1", name="ck_budgets_month"),
    )


class RecurringRecord(Base):
    """周期锚点与预期金额；暂停停止显示待核对期次，结束后不可恢复。"""

    __tablename__ = "recurring_plans"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    merchant: Mapped[str] = mapped_column(String(160))
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cadence: Mapped[str] = mapped_column(String(16))
    start_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_recurring_amount"),
        CheckConstraint("version > 0", name="ck_recurring_version"),
        CheckConstraint("cadence IN ('monthly', 'yearly')", name="ck_recurring_cadence"),
        CheckConstraint("status IN ('active', 'paused', 'ended')", name="ck_recurring_status"),
    )


class RecurringMatchRecord(Base):
    """一期一笔、一笔一期；源流水被撤销时自动解除关联，不保留虚构支付事实。"""

    __tablename__ = "recurring_matches"
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("recurring_plans.id", ondelete="CASCADE"), primary_key=True
    )
    due_date: Mapped[date] = mapped_column(Date, primary_key=True)
    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), unique=True
    )


class RecurringRevisionRecord(Base):
    """追加生效配置；初始配置保留在主记录，不覆盖历史月份。"""

    __tablename__ = "recurring_revisions"
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("recurring_plans.id", ondelete="CASCADE"), primary_key=True
    )
    effective_month: Mapped[date] = mapped_column(Date, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    merchant: Mapped[str] = mapped_column(String(160))
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cadence: Mapped[str] = mapped_column(String(16))
    start_date: Mapped[date] = mapped_column(Date)
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_recurring_revision_amount"),
        CheckConstraint("cadence IN ('monthly', 'yearly')", name="ck_recurring_revision_cadence"),
        CheckConstraint(
            "EXTRACT(DAY FROM effective_month) = 1", name="ck_recurring_revision_month"
        ),
    )


class RecurringSkipRecord(Base):
    """用户明确确认本期未发生；不创建交易，不修改预计扣款配置。"""

    __tablename__ = "recurring_skips"
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("recurring_plans.id", ondelete="CASCADE"), primary_key=True
    )
    due_date: Mapped[date] = mapped_column(Date, primary_key=True)


class AssistantActionRecord(Base):
    """冻结用户即将确认的预算差异；确认、写入和回执共用一个事务。"""

    __tablename__ = "assistant_actions"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="SET NULL"), index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    before_amount: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'applied', 'cancelled')", name="ck_assistant_action_status"
        ),
    )


class AssistantConversationRecord(Base):
    """Deleted records retain only ownership and creation identity to reject replay."""

    __tablename__ = "assistant_conversations"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    creation_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str | None] = mapped_column(String(80))
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    month: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (UniqueConstraint("user_id", "creation_id", name="uq_assistant_creation"),)


class AssistantTurnRecord(Base):
    __tablename__ = "assistant_turns"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[UUID] = mapped_column(Uuid)
    digest: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(8))
    month: Mapped[date] = mapped_column(Date)
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    business_date: Mapped[date] = mapped_column(Date)
    retry_of: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), default="processing")
    completion_token: Mapped[UUID] = mapped_column(Uuid, default=uuid4)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_version: Mapped[int] = mapped_column(Integer, default=1)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    action_id: Mapped[UUID | None] = mapped_column(ForeignKey("assistant_actions.id"))
    __table_args__ = (
        UniqueConstraint("conversation_id", "request_id", name="uq_assistant_request"),
        UniqueConstraint("conversation_id", "sequence", name="uq_assistant_sequence"),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')", name="ck_assistant_turn_status"
        ),
        Index(
            "uq_assistant_processing",
            "conversation_id",
            unique=True,
            postgresql_where=(status == "processing"),
        ),
    )
