"""
文件职责：定义 BankPilot 身份、账户、卡片、账务分析与 Agent 运行的 ORM 模型。

主要内容：
- 身份与账务：`UserRecord`、`SessionRecord`、`AccountRecord`、`CardRecord`、`TransactionRecord`。
- 分析修正：`TransactionCategoryOverrideRecord` 保存用户确认的交易分类。
- Agent 运行：`RunRecord` 保存状态、计划、结果、错误和模型信息。
- 审计记录：`AuditEventRecord` 按运行保存有序事件。

关键边界：所有业务归属通过外键表达；复合索引服务于归属和时间范围查询。
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bankpilot.db.base import Base
from bankpilot.domain.contracts import CardStatus, RunStatus


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    accounts: Mapped[list["AccountRecord"]] = relationship(cascade="all, delete-orphan")


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transactions: Mapped[list["TransactionRecord"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    cards: Mapped[list["CardRecord"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
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
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    merchant: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(500), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")

    account: Mapped[AccountRecord] = relationship(back_populates="transactions")

    __table_args__ = (Index("ix_transactions_account_occurred", "account_id", "occurred_at"),)


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
