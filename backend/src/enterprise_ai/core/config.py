"""Environment-driven application configuration."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings for currently implemented application behavior."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    auth_enabled: bool = False
    auth_token_secret: SecretStr | None = None
    auth_token_algorithm: Literal["HS256"] = "HS256"  # noqa: S105 - algorithm identifier
    auth_token_expiry_minutes: int = Field(default=30, ge=1, le=1_440)
    auth_token_issuer: str = Field(
        default="enterprise-ai-knowledge-assistant", min_length=1, max_length=200
    )
    auth_token_audience: str = Field(
        default="enterprise-ai-knowledge-assistant-api", min_length=1, max_length=200
    )
    demo_viewer_username: str = Field(default="demo-viewer", min_length=1, max_length=128)
    demo_viewer_password_hash: SecretStr | None = None
    demo_analyst_username: str = Field(default="demo-analyst", min_length=1, max_length=128)
    demo_analyst_password_hash: SecretStr | None = None
    demo_admin_username: str = Field(default="demo-admin", min_length=1, max_length=128)
    demo_admin_password_hash: SecretStr | None = None

    @model_validator(mode="after")
    def validate_authentication_configuration(self) -> Self:
        if not self.auth_enabled:
            return self
        required_secrets = (
            self.auth_token_secret,
            self.demo_viewer_password_hash,
            self.demo_analyst_password_hash,
            self.demo_admin_password_hash,
        )
        if any(secret is None or not secret.get_secret_value() for secret in required_secrets):
            raise ValueError(
                "authentication secrets and demonstration password hashes are required"
            )
        if self.auth_token_secret is None or len(self.auth_token_secret.get_secret_value()) < 32:
            raise ValueError("authentication signing secret must contain at least 32 characters")
        usernames = {
            self.demo_viewer_username.strip().casefold(),
            self.demo_analyst_username.strip().casefold(),
            self.demo_admin_username.strip().casefold(),
        }
        if len(usernames) != 3:
            raise ValueError("demonstration usernames must be unique after normalization")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""
    return Settings()
