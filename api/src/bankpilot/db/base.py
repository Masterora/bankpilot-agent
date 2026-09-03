"""
文件职责：提供 SQLAlchemy 声明式模型的统一基类。

主要内容：`Base` 被所有 ORM 模型继承，其 `metadata` 供 Alembic 迁移使用。
关键边界：本文件不定义业务表，避免模型注册与基类职责混杂。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
