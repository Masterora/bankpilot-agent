"""定义 BankPilot 的集中式运行配置。

生产环境不得使用默认会话密钥，敏感值统一使用 `SecretStr`。
"""

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量加载配置，并避免密钥以普通字符串形式暴露。"""

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    environment: str = Field(default="development", validation_alias="BANKPILOT_ENV")
    business_timezone: str = Field(default="Asia/Shanghai", validation_alias="BANKPILOT_TIMEZONE")
    database_url: str = Field(
        repr=False,
        default="postgresql+asyncpg://bankpilot:replace-me@db.internal:5432/bankpilot",
        validation_alias="BANKPILOT_DATABASE_URL",
    )
    session_secret: SecretStr = Field(
        default=SecretStr("development-only-change-this-secret"),
        validation_alias="BANKPILOT_SESSION_SECRET",
    )
    session_ttl_seconds: int = Field(
        default=28_800, validation_alias="BANKPILOT_SESSION_TTL_SECONDS"
    )
    session_cookie_secure: bool | None = Field(
        default=None, validation_alias="BANKPILOT_SESSION_COOKIE_SECURE"
    )
    cors_origins: str = Field(
        default="http://localhost:5173", validation_alias="BANKPILOT_CORS_ORIGINS"
    )
    recurring_discovery_enabled: bool = Field(
        default=False, validation_alias="BANKPILOT_RECURRING_DISCOVERY_ENABLED"
    )

    notifications_enabled: bool = Field(
        default=False, validation_alias="BANKPILOT_NOTIFICATIONS_ENABLED"
    )
    notification_epoch: str = Field(
        default="r7-v1",
        min_length=1,
        max_length=64,
        validation_alias="BANKPILOT_NOTIFICATION_EPOCH",
    )

    feishu_enabled: bool = Field(default=False, validation_alias="FEISHU_ENABLED")
    feishu_app_id: str = Field(default="", validation_alias="FEISHU_APP_ID")
    feishu_app_secret: SecretStr = Field(
        default=SecretStr(""), validation_alias="FEISHU_APP_SECRET"
    )
    feishu_encrypt_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="FEISHU_ENCRYPT_KEY"
    )
    feishu_verification_token: SecretStr = Field(
        default=SecretStr(""), validation_alias="FEISHU_VERIFICATION_TOKEN"
    )
    feishu_tenant_key: str = Field(default="", validation_alias="FEISHU_TENANT_KEY")
    alipay_sandbox_enabled: bool = Field(default=False, validation_alias="ALIPAY_SANDBOX_ENABLED")
    alipay_app_id: str = Field(default="", validation_alias="ALIPAY_SANDBOX_APP_ID")
    alipay_seller_id: str = Field(default="", validation_alias="ALIPAY_SANDBOX_SELLER_ID")
    alipay_private_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="ALIPAY_SANDBOX_PRIVATE_KEY"
    )
    alipay_public_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="ALIPAY_SANDBOX_PUBLIC_KEY"
    )
    integration_public_url: str = Field(default="", validation_alias="BANKPILOT_PUBLIC_URL")

    @model_validator(mode="after")
    def integration_configuration(self) -> "Settings":
        from urllib.parse import urlsplit

        if self.feishu_enabled and not all(
            (
                self.feishu_app_id,
                self.feishu_app_secret.get_secret_value(),
                self.feishu_encrypt_key.get_secret_value(),
                self.feishu_verification_token.get_secret_value(),
                self.feishu_tenant_key,
            )
        ):
            raise ValueError(
                "Feishu requires app credentials, Encrypt Key, Verification Token and tenant key"
            )
        if self.alipay_sandbox_enabled and not all(
            (
                self.alipay_app_id,
                self.alipay_seller_id,
                self.alipay_private_key.get_secret_value(),
                self.alipay_public_key.get_secret_value(),
            )
        ):
            raise ValueError("Alipay sandbox requires app ID, seller ID and RSA2 keys")
        if self.feishu_enabled or self.alipay_sandbox_enabled:
            url = urlsplit(self.integration_public_url)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in ("", "/")
            ):
                raise ValueError("BANKPILOT_PUBLIC_URL must be a public HTTPS origin")
        return self

    assistant_max_conversations: int = Field(default=100, ge=1, le=10000)
    assistant_max_turns: int = Field(default=200, ge=1, le=10000)
    assistant_max_result_chars: int = Field(default=400000, ge=1000, le=1000000)
    assistant_context_chars: int = Field(default=24000, ge=6000, le=100000)

    auth_global_per_minute: int = Field(default=60, ge=1, le=1000)
    auth_source_per_minute: int = Field(default=20, ge=1, le=1000)
    auth_account_per_minute: int = Field(default=8, ge=1, le=100)
    password_concurrency: int = Field(default=4, ge=1, le=32)
    model_user_active: int = Field(default=2, ge=1, le=32)
    model_global_active: int = Field(default=8, ge=1, le=128)
    model_user_jobs_daily: int = Field(default=40, ge=1, le=10000)
    model_global_jobs_daily: int = Field(default=400, ge=1, le=100000)
    model_user_attempts_daily: int = Field(default=240, ge=1, le=100000)
    model_global_attempts_daily: int = Field(default=2400, ge=1, le=1000000)
    model_user_tokens_daily: int = Field(default=2000000, ge=1000, le=1000000000)
    model_global_tokens_daily: int = Field(default=20000000, ge=1000, le=10000000000)
    stream_user_active: int = Field(default=2, ge=1, le=32)
    stream_global_active: int = Field(default=16, ge=1, le=256)

    model_provider: str = Field(default="openrouter", validation_alias="MODEL_PROVIDER")
    model_id: str = Field(default="", validation_alias="MODEL_ID")
    model_base_url: str = Field(
        default="https://openrouter.ai/api/v1", validation_alias="MODEL_BASE_URL"
    )
    model_timeout_seconds: float = Field(default=30, validation_alias="MODEL_TIMEOUT_SECONDS")
    model_max_retries: int = Field(default=1, validation_alias="MODEL_MAX_RETRIES")
    model_max_tokens: int = Field(
        default=1600, ge=256, le=8192, validation_alias="MODEL_MAX_TOKENS"
    )
    model_reasoning_effort: Literal["minimal", "low", "medium", "high"] = Field(
        default="low", validation_alias="MODEL_REASONING_EFFORT"
    )
    model_require_parameters: bool = Field(
        default=True, validation_alias="MODEL_REQUIRE_PARAMETERS"
    )
    model_data_collection: str = Field(default="deny", validation_alias="MODEL_DATA_COLLECTION")
    openrouter_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="OPENROUTER_API_KEY"
    )

    @field_validator("model_provider")
    @classmethod
    def only_openrouter(cls, value: str) -> str:
        if value != "openrouter":
            raise ValueError("MODEL_PROVIDER must be openrouter")
        return value

    @field_validator("business_timezone")
    @classmethod
    def valid_business_timezone(cls, value: str) -> str:
        """业务日期使用明确的 IANA 时区，避免依赖服务器时区或静默回退。"""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("BANKPILOT_TIMEZONE must be a valid IANA timezone") from exc
        return value

    @field_validator("model_id")
    @classmethod
    def explicit_model_id(cls, value: str) -> str:
        model_id = value.strip()
        if model_id == "openrouter/auto":
            raise ValueError("MODEL_ID must select an explicit model")
        return model_id

    @field_validator("session_secret")
    @classmethod
    def strong_session_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("BANKPILOT_SESSION_SECRET must contain at least 32 characters")
        return value

    @field_validator("model_data_collection")
    @classmethod
    def valid_data_collection(cls, value: str) -> str:
        if value not in {"allow", "deny"}:
            raise ValueError("MODEL_DATA_COLLECTION must be allow or deny")
        return value

    @model_validator(mode="after")
    def production_secret_must_be_replaced(self) -> "Settings":
        """禁止生产环境继续使用文档中的开发默认密钥。"""
        if self.is_production and (
            self.session_secret.get_secret_value() == "development-only-change-this-secret"
        ):
            raise ValueError("BANKPILOT_SESSION_SECRET must be replaced in production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.is_production


@lru_cache
def get_settings() -> Settings:
    """为每个应用进程缓存一份已校验的配置。"""
    return Settings()
