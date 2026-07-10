"""Identity and authorization data contracts without enforcement behavior."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, SecretStr, field_validator, model_validator

from enterprise_ai.models.common import ContractModel, UserId
from enterprise_ai.models.validation import ensure_utc_aware, validate_text_length


class UserRole(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMINISTRATOR = "administrator"


class AccessLevel(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"

    @property
    def rank(self) -> int:
        """Return the deterministic sensitivity rank without changing serialization."""
        return list(type(self)).index(self)


class ToolPermission(StrEnum):
    KNOWLEDGE_SEARCH = "knowledge_search"
    PYTHON_ANALYSIS = "python_analysis"
    MCP_TOOLS = "mcp_tools"
    ADMINISTRATIVE_TOOLS = "administrative_tools"
    INGESTION_MANAGEMENT = "ingestion_management"
    HUMAN_APPROVAL = "human_approval"


class UserIdentity(ContractModel):
    user_id: UserId
    username: Annotated[str, Field(min_length=1, max_length=128)]
    display_name: Annotated[str, Field(min_length=1, max_length=200)]
    role: UserRole

    @field_validator("username", "display_name")
    @classmethod
    def validate_names(cls, value: str) -> str:
        return validate_text_length(value, maximum=200)


class PublicUserProfile(UserIdentity):
    """User fields safe to serialize to clients."""


class AuthenticatedPrincipal(ContractModel):
    identity: UserIdentity
    permissions: frozenset[ToolPermission] = Field(default_factory=frozenset)
    authenticated_at: datetime
    expires_at: datetime

    @field_validator("authenticated_at", "expires_at")
    @classmethod
    def validate_timestamps(cls, value: datetime) -> datetime:
        return ensure_utc_aware(value)

    @model_validator(mode="after")
    def validate_expiry(self) -> Self:
        if self.expires_at <= self.authenticated_at:
            raise ValueError("expires_at must be after authenticated_at")
        return self


class LoginRequest(ContractModel):
    username: Annotated[str, Field(min_length=1, max_length=128)]
    password: SecretStr = Field(min_length=8, max_length=1024)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return validate_text_length(value, maximum=128)


class LoginResponse(ContractModel):
    user: PublicUserProfile
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: datetime) -> datetime:
        return ensure_utc_aware(value)
