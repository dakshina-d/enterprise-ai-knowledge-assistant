"""Strict HTTP transport contracts for authenticated chat delivery."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.models.common import ContractModel, utc_now
from enterprise_ai.models.events import AgentEvent
from enterprise_ai.models.validation import validate_text_length


class ChatRequest(ContractModel):
    """Client-owned chat fields; identity and execution policy are deliberately absent."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "examples": [
                {"message": "Who owns the payment-gateway service?"},
                {"message": "Summarize the password policy."},
                {"message": "Identify recurring payment incident causes.", "top_k": 8},
            ]
        },
    )

    message: Annotated[str, Field(min_length=1, max_length=4_000)]
    session_id: UUID | None = None
    top_k: Annotated[int, Field(ge=1, le=100)] = 5

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return validate_text_length(value, maximum=4_000)


class PublicAPIError(ContractModel):
    code: Annotated[str, Field(min_length=1, max_length=100)]
    message: Annotated[str, Field(min_length=1, max_length=500)]
    request_id: UUID
    retryable: bool = False


class PublicAPIErrorEnvelope(ContractModel):
    error: PublicAPIError


class ChatStreamEnvelope(ContractModel):
    """Application-owned JSON payload carried by one native SSE message."""

    event_id: UUID
    sequence: Annotated[int, Field(ge=0)]
    request_id: UUID
    trace_id: UUID
    session_id: UUID
    event_type: Annotated[str, Field(min_length=1, max_length=100)]
    timestamp: datetime = Field(default_factory=utc_now)
    agent_event: AgentEvent | None = None
    response: GraphOutput | None = None
    error: PublicAPIError | None = None
