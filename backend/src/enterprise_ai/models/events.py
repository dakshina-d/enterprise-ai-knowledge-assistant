"""Versioned public streaming-event contracts with allowlisted payload fields."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator

from enterprise_ai.models.common import (
    ContractModel,
    EventId,
    RequestId,
    SessionId,
    TraceId,
    new_identifier,
    utc_now,
)
from enterprise_ai.models.graph import Route
from enterprise_ai.models.tools import ToolName
from enterprise_ai.models.validation import ensure_utc_aware, validate_text_length

EVENT_VERSION = "1.0"


class AgentEventType(StrEnum):
    REQUEST_ACCEPTED = "request.accepted"
    GRAPH_STARTED = "graph.started"
    NODE_STARTED = "node.started"
    NODE_COMPLETED = "node.completed"
    NODE_FAILED = "node.failed"
    ROUTE_SELECTED = "route.selected"
    RETRIEVAL_STARTED = "retrieval.started"
    RETRIEVAL_COMPLETED = "retrieval.completed"
    TOOL_AUTHORIZATION_STARTED = "tool.authorization_started"
    TOOL_AUTHORIZED = "tool.authorized"
    TOOL_DENIED = "tool.denied"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    RESEARCH_BATCH_STARTED = "research.batch_started"
    RESEARCH_BATCH_COMPLETED = "research.batch_completed"
    VALIDATION_COMPLETED = "validation.completed"
    MEMORY_UPDATED = "memory.updated"
    MEMORY_LOAD_STARTED = "memory.load_started"
    MEMORY_LOADED = "memory.loaded"
    MEMORY_CONTEXT_RESOLVED = "memory.context_resolved"
    MEMORY_UPDATE_STARTED = "memory.update_started"
    MEMORY_EVICTED = "memory.evicted"
    MEMORY_FAILED = "memory.failed"
    RESPONSE_TOKEN = "response.token"  # noqa: S105 - event name, not a credential
    RESPONSE_COMPLETED = "response.completed"
    RESPONSE_FAILED = "response.failed"
    RESPONSE_GENERATION_STARTED = "response.generation_started"
    RESPONSE_GENERATION_COMPLETED = "response.generation_completed"
    RESPONSE_GENERATION_FAILED = "response.generation_failed"
    CITATION_VALIDATION_STARTED = "citation.validation_started"
    CITATION_VALIDATION_COMPLETED = "citation.validation_completed"
    CITATION_VALIDATION_FAILED = "citation.validation_failed"
    RESPONSE_REPAIR_STARTED = "response.repair_started"
    RESPONSE_REPAIR_COMPLETED = "response.repair_completed"
    RESPONSE_FALLBACK_USED = "response.fallback_used"


class AgentEventStatus(StrEnum):
    ACCEPTED = "accepted"
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    WARNING = "warning"
    DENIED = "denied"
    FAILED = "failed"


class PublicAgentEventPayload(ContractModel):
    """Allowlisted UI payload; deliberately excludes arbitrary mappings."""

    route: Route | None = None
    tool_name: ToolName | None = None
    result_count: Annotated[int | None, Field(ge=0)] = None
    successful_count: Annotated[int | None, Field(ge=0)] = None
    failed_count: Annotated[int | None, Field(ge=0)] = None
    recursion_depth: Annotated[int | None, Field(ge=0, le=3)] = None
    duration_ms: Annotated[int | None, Field(ge=0)] = None
    token: Annotated[str | None, Field(max_length=4_000)] = None
    error_code: Annotated[str | None, Field(max_length=100)] = None
    retryable: bool | None = None
    citation_count: Annotated[int | None, Field(ge=0)] = None
    turn_count: Annotated[int | None, Field(ge=0)] = None
    evidence_reference_count: Annotated[int | None, Field(ge=0)] = None
    context_used: bool | None = None
    evicted_turn_count: Annotated[int | None, Field(ge=0)] = None


class AgentEvent(ContractModel):
    event_id: EventId = Field(default_factory=new_identifier)
    event_type: AgentEventType
    event_version: Annotated[str, Field(pattern=r"^\d+\.\d+$")] = EVENT_VERSION
    sequence_number: Annotated[int, Field(ge=0)]
    request_id: RequestId
    session_id: SessionId
    trace_id: TraceId
    timestamp: datetime = Field(default_factory=utc_now)
    node: Annotated[str | None, Field(max_length=100)] = None
    status: AgentEventStatus
    public_message: Annotated[str, Field(min_length=1, max_length=500)]
    payload: PublicAgentEventPayload = Field(default_factory=PublicAgentEventPayload)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return ensure_utc_aware(value)

    @field_validator("public_message")
    @classmethod
    def validate_public_message(cls, value: str) -> str:
        return validate_text_length(value, maximum=500)

    def to_public_dict(self) -> dict[str, object]:
        """Serialize only fields defined by the public event contract."""
        return self.model_dump(mode="json")
