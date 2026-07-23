"""Validated frontend-only configuration."""

from functools import lru_cache
from typing import Self

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class FrontendSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FRONTEND_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    api_base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8000")
    request_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    stream_timeout_seconds: float = Field(default=90.0, ge=5.0, le=600.0)
    application_title: str = Field(
        default="Enterprise AI Knowledge Assistant",
        min_length=1,
        max_length=100,
    )
    maximum_activity_items: int = Field(default=100, ge=10, le=200)

    @model_validator(mode="after")
    def validate_api_origin(self) -> Self:
        url = self.api_base_url
        if (
            url.scheme not in {"http", "https"}
            or url.username is not None
            or url.password is not None
            or url.query is not None
            or url.fragment is not None
            or url.path not in {"", "/"}
        ):
            raise ValueError("frontend API base URL must be an HTTP origin")
        return self

    def endpoint(self, path: str) -> str:
        if not path.startswith("/"):
            raise ValueError("API endpoint path must be absolute")
        return f"{str(self.api_base_url).rstrip('/')}{path}"


@lru_cache
def get_frontend_settings() -> FrontendSettings:
    return FrontendSettings()
