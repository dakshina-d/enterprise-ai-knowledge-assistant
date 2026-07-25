"""Serializable graph-state contracts without orchestration behavior."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from enterprise_ai.models.chat import ChatMessage
from enterprise_ai.models.common import (
    ContractModel,
    EvidenceId,
    ProcessingStatus,
    RequestId,
    SessionId,
    TraceId,
    UserId,
)
from enterprise_ai.models.identity import UserRole
from enterprise_ai.models.retrieval import EvidenceItem, SearchPlan
from enterprise_ai.models.tools import ToolRequest, ToolResult


class Intent(StrEnum):
    SECURITY_DENIAL = "security_denial"
    CONVERSATIONAL = "conversational"
    KNOWLEDGE_LOOKUP = "knowledge_lookup"
    CROSS_DOCUMENT_RESEARCH = "cross_document_research"
    STRUCTURED_ANALYSIS = "structured_analysis"
    ENTERPRISE_TOOL_LOOKUP = "enterprise_tool_lookup"
    ADMINISTRATIVE = "administrative"
    UNSUPPORTED = "unsupported"


class Route(StrEnum):
    DIRECT_RESPONSE = "direct_response"
    SIMPLE_RETRIEVAL = "simple_retrieval"
    RECURSIVE_RESEARCH = "recursive_research"
    PYTHON_ANALYSIS = "python_analysis"
    MCP_TOOL = "mcp_tool"
    HUMAN_APPROVAL = "human_approval"
    DENY = "deny"
    UNSUPPORTED = "unsupported"
    FAILURE = "failure"


class ValidationResult(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


class ValidationFinding(ContractModel):
    code: Annotated[str, Field(min_length=1, max_length=100)]
    result: ValidationResult
    public_message: Annotated[str, Field(min_length=1, max_length=500)]


class ValidationReport(ContractModel):
    result: ValidationResult
    findings: tuple[ValidationFinding, ...] = ()


class IntermediateFinding(ContractModel):
    subtask_id: Annotated[str, Field(min_length=1, max_length=100)]
    summary: Annotated[str, Field(min_length=1, max_length=4_000)]
    evidence_ids: tuple[EvidenceId, ...] = ()
    warnings: tuple[Annotated[str, Field(max_length=500)], ...] = ()


class ResearchBatch(ContractModel):
    batch_id: Annotated[str, Field(min_length=1, max_length=100)]
    recursion_depth: Annotated[int, Field(ge=0, le=3)]
    plan: SearchPlan


class ResearchBatchResult(ContractModel):
    batch_id: Annotated[str, Field(min_length=1, max_length=100)]
    findings: tuple[IntermediateFinding, ...] = ()
    successful_subtasks: Annotated[int, Field(ge=0)]
    failed_subtasks: Annotated[int, Field(ge=0)]
    warnings: tuple[Annotated[str, Field(max_length=500)], ...] = ()


class RetryState(ContractModel):
    attempts: Annotated[int, Field(ge=0)] = 0
    maximum_attempts: Annotated[int, Field(ge=0, le=5)] = 2

    @model_validator(mode="after")
    def validate_attempts(self) -> Self:
        if self.attempts > self.maximum_attempts:
            raise ValueError("attempts cannot exceed maximum_attempts")
        return self


class GraphError(ContractModel):
    code: Annotated[str, Field(min_length=1, max_length=100)]
    safe_message: Annotated[str, Field(min_length=1, max_length=500)]
    retryable: bool = False
    node: Annotated[str | None, Field(max_length=100)] = None


class GraphStateSnapshot(ContractModel):
    """Checkpoint-safe state excluding prompts, secrets, and private reasoning."""

    request_id: RequestId
    trace_id: TraceId
    session_id: SessionId
    user_id: UserId
    user_role: UserRole
    messages: tuple[ChatMessage, ...] = ()
    normalized_query: Annotated[str | None, Field(max_length=4_000)] = None
    detected_intent: Intent | None = None
    route: Route | None = None
    search_plan: SearchPlan | None = None
    retrieved_evidence: tuple[EvidenceItem, ...] = ()
    tool_requests: tuple[ToolRequest, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    intermediate_findings: tuple[IntermediateFinding, ...] = ()
    recursion_depth: Annotated[int, Field(ge=0, le=3)] = 0
    maximum_recursion_depth: Annotated[int, Field(ge=0, le=3)] = 2
    remaining_task_budget: Annotated[int, Field(ge=0, le=100)] = 20
    remaining_time_budget_seconds: Annotated[float, Field(ge=0.0, le=3600.0)] = 60.0
    retry_state: RetryState = Field(default_factory=RetryState)
    validation_reports: tuple[ValidationReport, ...] = ()
    warnings: tuple[Annotated[str, Field(max_length=500)], ...] = ()
    errors: tuple[GraphError, ...] = ()
    response_draft: Annotated[str | None, Field(max_length=32_000)] = None
    final_response: Annotated[str | None, Field(max_length=32_000)] = None
    current_status: ProcessingStatus = ProcessingStatus.ACCEPTED

    @model_validator(mode="after")
    def validate_recursion_depth(self) -> Self:
        if self.recursion_depth > self.maximum_recursion_depth:
            raise ValueError("recursion_depth cannot exceed maximum_recursion_depth")
        return self


class PublicAgentStatus(ContractModel):
    request_id: RequestId
    status: ProcessingStatus
    node: Annotated[str | None, Field(max_length=100)] = None
    public_message: Annotated[str, Field(min_length=1, max_length=500)]
    route: Route | None = None
    recursion_depth: Annotated[int | None, Field(ge=0, le=3)] = None
