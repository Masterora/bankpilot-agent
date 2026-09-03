"""
文件职责：配置 Alembic 数据库迁移的运行环境。

主要内容：
- 从应用配置注入数据库 URL，并绑定 ORM `Base.metadata`。
- `do_run_migrations`：配置上下文并执行同步迁移。
- `run_async_migrations`：在线模式下通过异步引擎运行迁移。
- 离线分支：生成带字面值的 SQL。

关键边界：迁移引擎使用 `NullPool`，执行完成后立即释放。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from bankpilot.config import get_settings
from bankpilot.db import models  # noqa: F401
from bankpilot.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def do_run_migrations(connection: object) -> None:
    """在异步引擎的桥接连接上执行同步 Alembic 操作。"""
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """创建仅供迁移使用的引擎，升级完成后立即释放。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    import asyncio

    asyncio.run(run_async_migrations())
