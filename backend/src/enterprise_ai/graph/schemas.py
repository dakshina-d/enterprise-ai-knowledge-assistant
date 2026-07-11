"""Strict graph input, output, topology, and stream contracts."""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from enterprise_ai.models.common import ContractModel, ProcessingStatus, utc_now
from enterprise_ai.models.events import AgentEvent
from enterprise_ai.models.graph import Intent, PublicAgentStatus, Route, ValidationReport
from enterprise_ai.models.identity import AccessLevel, AuthenticatedPrincipal
from enterprise_ai.models.validation import validate_text_length
from enterprise_ai.retrieval.filters import DenseQueryFilters
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.tools.python_analysis.models import AnalysisResult


class GraphInput(ContractModel):
    request_id: UUID
    trace_id: UUID
    session_id: UUID
    principal: AuthenticatedPrincipal
    user_message: Annotated[str, Field(min_length=1, max_length=4_000)]
    retrieval_filters: DenseQueryFilters = Field(default_factory=DenseQueryFilters)
    requested_top_k: Annotated[int, Field(ge=1, le=100)] = 5
    invocation_timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("user_message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return validate_text_length(value, maximum=4_000)


class GraphEvidenceAttribution(ContractModel):
    evidence_id: UUID
    chunk_id: UUID
    document_id: UUID
    title: str
    source_file: str
    section: str
    source_line_start: int
    source_line_end: int
    access_level: AccessLevel
    hybrid_score: Annotated[float, Field(ge=0, le=1)]
    final_rank: Annotated[int, Field(ge=1)]
    retrieval_modes: frozenset[str]

    @classmethod
    def from_hybrid(cls, item: HybridEvidence) -> "GraphEvidenceAttribution":
        evidence = item.evidence
        return cls(
            evidence_id=evidence.evidence_id,
            chunk_id=evidence.chunk_id,
            document_id=evidence.document_id,
            title=evidence.title,
            source_file=evidence.source_file,
            section=evidence.section,
            source_line_start=evidence.source_line_start,
            source_line_end=evidence.source_line_end,
            access_level=evidence.access_level,
            hybrid_score=item.hybrid_score,
            final_rank=item.final_rank,
            retrieval_modes=item.retrieval_modes,
        )


class GraphOutput(ContractModel):
    graph_version: str
    request_id: UUID
    trace_id: UUID
    session_id: UUID
    completion_status: ProcessingStatus
    selected_route: Route
    intent: Intent
    evidence: tuple[GraphEvidenceAttribution, ...] = ()
    warnings: tuple[str, ...] = ()
    response_text: str
    validation_reports: tuple[ValidationReport, ...] = ()
    agent_status: PublicAgentStatus
    memory_used: bool = False
    context_resolved: bool = False
    turn_sequence: int | None = None
    memory_update_status: str = "disabled"
    analysis_result: AnalysisResult | None = None


class GraphStreamItem(ContractModel):
    event: AgentEvent | None = None
    output: GraphOutput | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> Self:
        if (self.event is None) == (self.output is None):
            raise ValueError("stream item must contain exactly one public value")
        return self


class GraphTopology(ContractModel):
    graph_version: str
    entry_point: str
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    conditional_routes: dict[str, str]
    terminal_nodes: tuple[str, ...]
    implemented_capabilities: tuple[str, ...]
    planned_capabilities: tuple[str, ...]
