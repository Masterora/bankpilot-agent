"""
文件职责：提供 BankPilot 的显式运维命令行入口。

主要内容：
- `seed`：校验邮箱和密码，触发异步初始化。
- `_seed`：幂等创建本地用户、账户、卡片与可重复验证的交易记录。

关键边界：密码仅从交互输入或环境变量读取，入库前必须哈希；引擎在命令结束时释放。
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import typer
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select

from bankpilot.config import get_settings
from bankpilot.db.models import AccountRecord, CardRecord, TransactionRecord
from bankpilot.db.repositories import UserRepository
from bankpilot.db.session import create_engine, create_session_factory
from bankpilot.domain.contracts import CardStatus
from bankpilot.security import hash_password

app = typer.Typer(no_args_is_help=True)


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
    if len(password) < 12:
        raise typer.BadParameter("password must contain at least 12 characters")
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
