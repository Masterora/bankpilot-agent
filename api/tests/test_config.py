"""
文件职责：验证生产会话 Cookie 的安全配置推导。
主要内容：覆盖生产默认开启 Secure，以及私网 HTTP 部署的显式关闭选项。
关键边界：只允许通过明确配置覆盖生产默认值。
"""

from bankpilot.config import Settings


def test_production_cookie_is_secure_by_default() -> None:
    settings = Settings(
        BANKPILOT_ENV="production",
        BANKPILOT_SESSION_SECRET="test-secret-with-more-than-32-characters",
    )

    assert settings.cookie_secure is True


def test_private_http_deployment_can_disable_secure_cookie() -> None:
    settings = Settings(
        BANKPILOT_ENV="production",
        BANKPILOT_SESSION_SECRET="test-secret-with-more-than-32-characters",
        BANKPILOT_SESSION_COOKIE_SECURE="false",
    )

    assert settings.cookie_secure is False
