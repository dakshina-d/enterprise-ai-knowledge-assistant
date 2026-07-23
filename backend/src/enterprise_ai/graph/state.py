"""Typed reducer-aware internal LangGraph state."""

from datetime import datetime
from typing import Annotated, TypedDict
from uuid import UUID

from enterprise_ai.graph.reducers import append_events, append_text, append_unique
from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.llm.models import (
    CitationValidationResult,
    GroundedAnswerDraft,
    GroundedResponse,
    ResponseMode,
)
from enterprise_ai.mcp_tools.models import MCPExecutionResult
from enterprise_ai.memory.models import MemoryContext
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import AgentEvent
from enterprise_ai.models.graph import GraphError, Intent, Route, ValidationReport
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.research.models import ResearchResult
from enterprise_ai.retrieval.filters import DenseQueryFilters
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.tools.python_analysis.models import AnalysisRequest, AnalysisResult


class GraphState(TypedDict, total=False):
    request_id: UUID
    trace_id: UUID
    session_id: UUID
    principal: AuthenticatedPrincipal
    user_message: str
    original_query: str
    resolved_query: str
    normalized_query: str
    detected_intent: Intent
    task_complexity: str
    selected_route: Route
    retrieval_filters: DenseQueryFilters
    requested_top_k: int
    retrieved_evidence: Annotated[tuple[HybridEvidence, ...], append_unique]
    validation_reports: Annotated[tuple[ValidationReport, ...], append_unique]
    warnings: Annotated[tuple[str, ...], append_text]
    errors: Annotated[tuple[GraphError, ...], append_unique]
    visited_nodes: Annotated[tuple[str, ...], append_text]
    activity_events: Annotated[tuple[AgentEvent, ...], append_events]
    response_text: str
    processing_status: ProcessingStatus
    active_node: str
    execution_started_at: datetime
    deadline: datetime
    execution_step_count: int
    maximum_execution_steps: int
    maximum_recursion_depth: int
    retrieval_status: str
    failure: bool
    final_output: GraphOutput
    invocation_timestamp: datetime
    conversation_context: MemoryContext
    memory_used: bool
    context_reference_detected: bool
    context_used: bool
    memory_update_status: str
    memory_eviction_count: int
    current_turn_sequence: int
    analysis_request: AnalysisRequest
    analysis_result: AnalysisResult
    response_mode: ResponseMode
    grounded_answer_draft: GroundedAnswerDraft
    citation_validation: CitationValidationResult
    grounded_response: GroundedResponse
    response_repair_count: int
    provider_status: str
    deterministic_fallback_used: bool
    research_result: ResearchResult
    mcp_execution: MCPExecutionResult
