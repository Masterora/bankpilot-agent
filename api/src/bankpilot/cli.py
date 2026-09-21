"""
文件职责：提供 BankPilot 的显式运维命令行入口。

主要内容：
- `seed`：校验邮箱和密码，触发异步初始化。
- `_seed`：幂等创建本地用户、账户、卡片与可重复验证的交易记录。
- `backup-db / restore-db / restore-check / restore-prepare`：显式离线备份与恢复。

关键边界：密码仅从交互输入或环境变量读取，入库前必须哈希；引擎在命令结束时释放。
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select

from bankpilot.config import get_settings
from bankpilot.db.ledger_revision import bump_revision
from bankpilot.db.models import AccountRecord, CardRecord, TransactionRecord
from bankpilot.db.session import create_engine, create_session_factory
from bankpilot.db.user_repository import UserRepository
from bankpilot.domain.contracts import CardStatus
from bankpilot.security import hash_password, validate_new_password

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


@app.callback()
def main() -> None:
    """BankPilot 运维命令。"""


@app.command()
def seed(
    email: str = typer.Option(..., envvar="BANKPILOT_SEED_EMAIL", prompt=True),
    password: str = typer.Option(
        ...,
        envvar="BANKPILOT_SEED_PASSWORD",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
    ),
) -> None:
    """创建本地用户与可重复验证的本地银行记录。"""
    TypeAdapter(EmailStr).validate_python(email)
    try:
        validate_new_password(password)
    except ValueError as exc:
        raise typer.BadParameter(
            "password must contain 8 to 128 characters, including uppercase, "
            "lowercase, number and symbol"
        ) from exc
    asyncio.run(_seed(email, password))


async def _seed(email: str, password: str) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session, session.begin():
            users = UserRepository(session)
            user = await users.by_email(email)
            if user is None:
                user = await users.add(email=email, password_hash=hash_password(password))
            account = await session.scalar(
                select(AccountRecord).where(
                    AccountRecord.user_id == user.id,
                    AccountRecord.name == "日常账户",
                )
            )
            if account is None:
                account = AccountRecord(user_id=user.id, name="日常账户", currency="CNY")
                session.add(account)
                await session.flush()
                now = datetime.now(UTC)
                session.add_all(
                    [
                        TransactionRecord(
                            account_id=account.id,
                            booking_date=(now - timedelta(days=2)).date(),
                            occurred_at=now - timedelta(days=2),
                            merchant="城市交通",
                            description="通勤",
                            amount=Decimal("-6.00"),
                            currency="CNY",
                        ),
                        TransactionRecord(
                            account_id=account.id,
                            booking_date=(now - timedelta(days=5)).date(),
                            occurred_at=now - timedelta(days=5),
                            merchant="社区超市",
                            description="日用品",
                            amount=Decimal("-128.50"),
                            currency="CNY",
                        ),
                        TransactionRecord(
                            account_id=account.id,
                            booking_date=(now - timedelta(days=10)).date(),
                            occurred_at=now - timedelta(days=10),
                            merchant="工资入账",
                            description="月度工资",
                            amount=Decimal("12000.00"),
                            currency="CNY",
                        ),
                    ]
                )
                await bump_revision(session, user.id)
            card = await session.scalar(
                select(CardRecord).where(
                    CardRecord.account_id == account.id,
                    CardRecord.display_name == "日常卡",
                )
            )
            if card is None:
                # 只写展示所需的卡片尾号，初始化流程不接触或保存完整卡号。
                session.add(
                    CardRecord(
                        account_id=account.id,
                        display_name="日常卡",
                        last_four="1024",
                        status=CardStatus.ACTIVE.value,
                    )
                )
        typer.echo(f"Local banking data is ready for {email.lower()}")
    finally:
        await engine.dispose()


def _operation_url(variable: str) -> str:
    value = os.environ.get(variable)
    if not value:
        raise typer.BadParameter(f"{variable} must be explicitly set")
    return value


@app.command("backup-db")
def backup_db(
    directory: Annotated[Path, typer.Option()],
    application_commit: Annotated[str, typer.Option()],
) -> None:
    """备份到新建受限目录；使用加密磁盘并另行保留异机副本。"""
    from bankpilot.services.database_backup import backup_database

    os.umask(0o077)
    result = asyncio.run(
        backup_database(
            _operation_url("BANKPILOT_BACKUP_DATABASE_URL"),
            directory,
            application_commit,
        )
    )
    typer.echo(json.dumps(result))


@app.command("restore-db")
def restore_db(
    directory: Annotated[Path, typer.Option()], expected_db: Annotated[str, typer.Option()]
) -> None:
    """仅还原到无其他客户端的空库，完成后核对完整备份证据。"""
    from bankpilot.services.database_backup import restore_database

    os.umask(0o077)
    result = asyncio.run(
        restore_database(
            _operation_url("BANKPILOT_RESTORE_DATABASE_URL"),
            directory,
            expected_db,
        )
    )
    typer.echo(json.dumps(result))


@app.command("restore-check")
def restore_check(
    directory: Annotated[Path, typer.Option()], expected_db: Annotated[str, typer.Option()]
) -> None:
    """不启动应用，在只读一致性快照核对所有表和历史报告。"""
    from bankpilot.services.database_backup import check_restored

    result = asyncio.run(
        check_restored(
            _operation_url("BANKPILOT_RESTORE_DATABASE_URL"),
            directory,
            expected_db,
        )
    )
    typer.echo(json.dumps(result))


@app.command("restore-prepare")
def restore_prepare(
    directory: Annotated[Path, typer.Option()],
    expected_db: Annotated[str, typer.Option()],
    apply: Annotated[bool, typer.Option("--apply")] = False,
    clear_assistant_history: Annotated[bool, typer.Option("--clear-assistant-history")] = False,
) -> None:
    """默认仅报告中断任务数量；--apply 原子失效旧任务令牌和会话。"""
    from bankpilot.services.database_backup import check_restored

    if apply and not clear_assistant_history:
        raise typer.BadParameter(
            "--apply requires --clear-assistant-history; all restored chats will be cleared"
        )
    if apply:
        typer.echo(
            f"Restore target: {expected_db}. Clear all assistant history; "
            "retain ledger, budgets and applied receipts."
        )
        typer.confirm("Clear ALL assistant history in this isolated restore database?", abort=True)
    os.umask(0o077)
    result = asyncio.run(
        check_restored(
            _operation_url("BANKPILOT_RESTORE_DATABASE_URL"),
            directory,
            expected_db,
            prepare=True,
            clear_assistant_history=clear_assistant_history,
            apply=apply,
        )
    )
    typer.echo(json.dumps(result))
