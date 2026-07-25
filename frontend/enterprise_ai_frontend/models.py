"""Frontend presentation state built only from public backend contracts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.llm.models import FallbackReason, VerifiedCitation
from enterprise_ai.mcp_tools.models import MCPProvenance
from enterprise_ai.models.common import ContractModel, ProcessingStatus, utc_now
from enterprise_ai.models.events import AgentEventStatus
from enterprise_ai.models.graph import Route
from enterprise_ai.models.identity import UserRole
from enterprise_ai.tools.python_analysis.models import AnalysisResult
from pydantic import Field


class FrontendUser(ContractModel):
    username: Annotated[str, Field(min_length=1, max_length=128)]
    display_name: Annotated[str, Field(min_length=1, max_length=200)]
    role: UserRole


class ChatMessage(ContractModel):
    message_id: UUID
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=32_000)]
    created_at: datetime = Field(default_factory=utc_now)
    completion_status: ProcessingStatus | None = None
    selected_route: Route | None = None
    request_id: UUID | None = None
    citations: tuple[VerifiedCitation, ...] = ()
    mcp_provenance: MCPProvenance | None = None
    analysis_operation: Annotated[str | None, Field(max_length=100)] = None
    insufficient_evidence: bool = False
    deterministic_fallback_used: bool = False
    deterministic_analysis_rendering_used: bool = False
    fallback_reason: FallbackReason | None = None
    analysis_result: AnalysisResult | None = None


class ActivityItem(ContractModel):
    event_id: UUID
    sequence: Annotated[int, Field(ge=0)]
    timestamp: datetime
    event_type: Annotated[str, Field(min_length=1, max_length=100)]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    status: AgentEventStatus | Literal["started", "failed", "completed"]
    detail: Annotated[str | None, Field(max_length=300)] = None


class RequestMetadata(ContractModel):
    request_id: UUID
    trace_id: UUID
    session_id: UUID


class CompletedTurn(ContractModel):
    output: GraphOutput
    assistant_message: ChatMessage
