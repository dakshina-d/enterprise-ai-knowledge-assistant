"""Common identifiers, timestamps, statuses, and pagination contracts."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_ai.models.validation import ensure_utc_aware

type RequestId = UUID
type TraceId = UUID
type SessionId = UUID
type UserId = UUID
type DocumentId = UUID
type ChunkId = UUID
type ToolCallId = UUID
type EventId = UUID
type MessageId = UUID
type FeedbackId = UUID
type EvidenceId = UUID

PositiveLimit = Annotated[int, Field(ge=1, le=100)]


def new_identifier() -> UUID:
    """Generate an opaque UUID identifier."""
    return uuid4()


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(UTC)


class ContractModel(BaseModel):
    """Strict immutable base for shared contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TimestampedModel(ContractModel):
    """Base model with an automatically generated UTC timestamp."""

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return ensure_utc_aware(value)


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class ProcessingStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    PARTIAL_SUCCESS = "partial_success"
    COMPLETED = "completed"
    DENIED = "denied"
    FAILED = "failed"


class PaginationRequest(ContractModel):
    limit: PositiveLimit = 20
    cursor: Annotated[str | None, Field(max_length=512)] = None


class PaginationMetadata(ContractModel):
    limit: PositiveLimit
    returned: Annotated[int, Field(ge=0)]
    next_cursor: Annotated[str | None, Field(max_length=512)] = None
    total: Annotated[int | None, Field(ge=0)] = None

    @model_validator(mode="after")
    def validate_returned_count(self) -> Self:
        if self.returned > self.limit:
            raise ValueError("returned cannot exceed limit")
        return self
