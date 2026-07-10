"""Generic, bounded tool and human-approval contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator

from enterprise_ai.models.common import (
    ContractModel,
    RequestId,
    ToolCallId,
    UserId,
    new_identifier,
)
from enterprise_ai.models.identity import ToolPermission
from enterprise_ai.models.validation import JsonValue, ensure_utc_aware, validate_json_compatible

MAX_TOOL_PAYLOAD_BYTES = 16_384
MAX_TOOL_PAYLOAD_DEPTH = 5


class ToolName(StrEnum):
    KNOWLEDGE_SEARCH = "knowledge_search"
    PYTHON_ANALYSIS = "python_analysis"
    EMPLOYEE_DIRECTORY = "employee_directory"
    SERVICE_CATALOG = "service_catalog"
    INCIDENT_RECORDS = "incident_records"
    ADMINISTRATIVE_INGESTION = "administrative_ingestion"


class ToolExecutionStatus(StrEnum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    DENIED = "denied"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class ToolRequest(ContractModel):
    tool_call_id: ToolCallId = Field(default_factory=new_identifier)
    request_id: RequestId
    tool_name: ToolName
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        validate_json_compatible(
            value,
            maximum_depth=MAX_TOOL_PAYLOAD_DEPTH,
            maximum_bytes=MAX_TOOL_PAYLOAD_BYTES,
        )
        return value


class ToolAuthorizationDecision(ContractModel):
    tool_call_id: ToolCallId
    allowed: bool
    reason_code: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_.-]+$")]
    public_explanation: Annotated[str, Field(min_length=1, max_length=500)]
    required_permission: ToolPermission | None


class ToolExecutionMetadata(ContractModel):
    duration_ms: Annotated[int, Field(ge=0)]
    attempt: Annotated[int, Field(ge=1)] = 1
    provider_request_id: Annotated[str | None, Field(max_length=200)] = None


class ToolResult(ContractModel):
    tool_call_id: ToolCallId
    tool_name: ToolName
    status: ToolExecutionStatus
    safe_data: JsonValue
    warnings: tuple[Annotated[str, Field(max_length=500)], ...] = ()
    metadata: ToolExecutionMetadata

    @field_validator("safe_data")
    @classmethod
    def validate_safe_data(cls, value: JsonValue) -> JsonValue:
        return validate_json_compatible(value, maximum_bytes=MAX_TOOL_PAYLOAD_BYTES)


class ToolError(ContractModel):
    tool_call_id: ToolCallId
    tool_name: ToolName
    code: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_.-]+$")]
    safe_message: Annotated[str, Field(min_length=1, max_length=500)]
    retryable: bool = False


class HumanApprovalRequest(ContractModel):
    approval_id: ToolCallId = Field(default_factory=new_identifier)
    tool_call_id: ToolCallId
    requested_by: UserId
    public_summary: Annotated[str, Field(min_length=1, max_length=1_000)]
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: datetime) -> datetime:
        return ensure_utc_aware(value)


class HumanApprovalDecision(ContractModel):
    approval_id: ToolCallId
    approved: bool
    decided_by: UserId
    reason_code: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_.-]+$")]
    public_explanation: Annotated[str | None, Field(max_length=500)] = None
    decided_at: datetime

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at(cls, value: datetime) -> datetime:
        return ensure_utc_aware(value)
