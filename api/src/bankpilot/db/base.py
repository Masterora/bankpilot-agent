"""
文件职责：提供 SQLAlchemy 声明式基类与配套数据库版本标识。
主要内容：Base.metadata 供模型注册和迁移使用，SCHEMA_REVISION 供备份恢复结构核对。
关键边界：不定义业务表；版本标识必须与实际模型和迁移一致。
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# 与本应用 ORM 模型配套的数据库版本；备份证据拒绝不同版本。
SCHEMA_REVISION = "20260921_0014"
