"""
文件职责：验证运维命令行的公开入口。
主要内容：确认 `seed` 命令已注册并出现在帮助信息中。
关键边界：本测试只验证命令契约，不写入数据库。
"""

from typer.testing import CliRunner

from bankpilot.cli import app


def test_seed_is_exposed_as_subcommand() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "seed" in result.output
