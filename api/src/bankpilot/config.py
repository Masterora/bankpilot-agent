"""
文件职责：定义 BankPilot 的集中式运行配置。

主要内容：
- `Settings`：数据库、会话、CORS 和 OpenRouter 配置。
- 字段校验器：限制模型供应商、模型 ID、密钥强度与数据收集策略。
- `get_settings`：返回进程内缓存的配置实例。

关键边界：生产环境不得使用默认会话密钥，敏感值统一使用 `SecretStr`。
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量加载配置，并避免密钥以普通字符串形式暴露。"""

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    environment: str = Field(default="development", validation_alias="BANKPILOT_ENV")
    database_url: str = Field(
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
    def only_openrouter_for_v01(cls, value: str) -> str:
        if value != "openrouter":
            raise ValueError("v0.1 only ships the OpenRouter adapter")
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
