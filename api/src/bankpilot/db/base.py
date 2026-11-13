"""提供 SQLAlchemy 声明式基类与配套数据库版本标识。

不定义业务表；版本标识必须与实际模型和迁移一致。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# 与本应用 ORM 模型配套的数据库版本；备份证据拒绝不同版本。
SCHEMA_REVISION = "20261016_0024"
