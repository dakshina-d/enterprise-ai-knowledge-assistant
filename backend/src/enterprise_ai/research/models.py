"""Immutable contracts for bounded recursive research."""

from datetime import date
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field

from enterprise_ai.models.common import ContractModel
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.research.structured_conflicts import StructuredConflict
from enterprise_ai.retrieval.filters import DenseQueryFilters
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.tools.python_analysis.models import AnalysisResult

RESEARCH_SCHEMA_VERSION = "1.0"
RESEARCH_PLANNER_VERSION = "fake-1.0"


class ResearchTaskType(StrEnum):
    TARGETED_LOOKUP = "targeted_lookup"
    POLICY_LOOKUP = "policy_lookup"
    INCIDENT_LOOKUP = "incident_lookup"
    ARCHITECTURE_LOOKUP = "architecture_lookup"
    RUNBOOK_LOOKUP = "runbook_lookup"
    TIMELINE_LOOKUP = "timeline_lookup"
    COMPARISON_DIMENSION = "comparison_dimension"
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    FREQUENCY_ANALYSIS = "frequency_analysis"
    GAP_INVESTIGATION = "gap_investigation"


class ResearchTaskStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"


class CoverageStatus(StrEnum):
    SUFFICIENT = "sufficient"
    PARTIALLY_SUFFICIENT = "partially_sufficient"
    INSUFFICIENT = "insufficient"
    BLOCKED_BY_AUTHORIZATION = "blocked_by_authorization"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"


class ResearchTaskDependency(ContractModel):
    task_id: str


class ResearchSearchStrategy(ContractModel):
    queries: tuple[Annotated[str, Field(min_length=1, max_length=1_000)], ...]
    filters: DenseQueryFilters = Field(default_factory=DenseQueryFilters)
    top_k: int = Field(default=5, ge=1, le=20)


class ResearchTask(ContractModel):
    task_id: str
    parent_task_id: str | None = None
    depth: int = Field(ge=0, le=5)
    task_type: ResearchTaskType
    research_question: Annotated[str, Field(min_length=1, max_length=2_000)]
    search: ResearchSearchStrategy
    expected_evidence_type: str = "document"
    dependency_task_ids: tuple[str, ...] = ()
    priority: int = Field(default=50, ge=0, le=100)
    analysis_may_be_useful: bool = False
    completion_criteria: tuple[str, ...] = ()


class CollectionCatalog(ContractModel):
    schema_version: str = RESEARCH_SCHEMA_VERSION
    build_fingerprint: str
    document_count: int
    departments: tuple[str, ...]
    document_types: tuple[str, ...]
    statuses: tuple[str, ...]
    earliest_date: date | None = None
    latest_date: date | None = None
    tags: tuple[str, ...] = ()
    incident_count: int = 0
    policy_count: int = 0
    runbook_count: int = 0
    architecture_document_count: int = 0


class ResearchRequest(ContractModel):
    question: str
    principal: AuthenticatedPrincipal
    request_id: UUID
    trace_id: UUID
    session_id: UUID


class ResearchPlan(ContractModel):
    plan_id: str
    original_question: str
    normalized_objective: str
    research_scope: str
    authorized_collection_summary: CollectionCatalog
    tasks: tuple[ResearchTask, ...]
    expected_synthesis_dimensions: tuple[str, ...] = ()
    required_comparison_dimensions: tuple[str, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    completion_criteria: tuple[str, ...] = ()
    planner_version: str = RESEARCH_PLANNER_VERSION
    maximum_depth: int = 2
    maximum_tasks: int = 12
    warnings: tuple[str, ...] = ()


class ResearchChildTaskProposal(ContractModel):
    parent_task_id: str
    task_type: ResearchTaskType
    research_question: str
    queries: tuple[str, ...]
    reason: str


class ResearchWorkerInput(ContractModel):
    principal: AuthenticatedPrincipal
    task: ResearchTask
    request_id: UUID
    trace_id: UUID
    session_id: UUID


class ResearchWorkerResult(ContractModel):
    task_id: str
    parent_task_id: str | None
    depth: int
    status: ResearchTaskStatus
    queries_executed: tuple[str, ...]
    retrieval_modes: tuple[str, ...]
    evidence: tuple[HybridEvidence, ...]
    coverage_status: CoverageStatus
    gaps: tuple[str, ...] = ()
    child_task_proposals: tuple[ResearchChildTaskProposal, ...] = ()
    warnings: tuple[str, ...] = ()
    error_category: str | None = None
    duration_seconds: float = Field(default=0, ge=0)
    retrieval_calls: int = Field(default=0, ge=0)
    analysis_calls: int = Field(default=0, ge=0)
    analysis_result: AnalysisResult | None = None


class ResearchEvidenceEntry(ContractModel):
    evidence: HybridEvidence
    task_ids: tuple[str, ...]


class ResearchEvidenceLedger(ContractModel):
    entries: tuple[ResearchEvidenceEntry, ...] = ()
    total_characters: int = 0
    dropped_items: int = 0


class ResearchGap(ContractModel):
    dimension: str
    reason: str
    task_id: str | None = None


class ResearchConflict(ContractModel):
    conflict_type: str
    evidence_ids: tuple[UUID, ...]
    description: str
    preferred_evidence_id: UUID | None = None


class ResearchCoverageAssessment(ContractModel):
    status: CoverageStatus
    covered_dimensions: tuple[str, ...] = ()
    missing_dimensions: tuple[str, ...] = ()
    unsupported_requested_claims: tuple[str, ...] = ()
    evidence_diversity: int = 0
    source_authority_distribution: tuple[tuple[str, int], ...] = ()
    conflicts: tuple[ResearchConflict, ...] = ()
    another_round_justified: bool = False


class ResearchBudget(ContractModel):
    maximum_depth: int
    maximum_total_tasks: int
    maximum_retrieval_calls: int
    maximum_analysis_calls: int
    maximum_llm_calls: int
    maximum_evidence_items: int
    maximum_evidence_characters: int


class ResearchBudgetUsage(ContractModel):
    tasks: int = 0
    retrieval_calls: int = 0
    analysis_calls: int = 0
    llm_calls: int = 0
    evidence_items: int = 0
    evidence_characters: int = 0
    exhausted: bool = False


class ResearchProvenance(ContractModel):
    schema_version: str = RESEARCH_SCHEMA_VERSION
    planner_version: str = RESEARCH_PLANNER_VERSION
    build_fingerprint: str


class ResearchResult(ContractModel):
    plan: ResearchPlan
    worker_results: tuple[ResearchWorkerResult, ...]
    evidence_ledger: ResearchEvidenceLedger
    coverage: ResearchCoverageAssessment
    gaps: tuple[ResearchGap, ...]
    conflicts: tuple[ResearchConflict, ...]
    budget_usage: ResearchBudgetUsage
    provenance: ResearchProvenance
    warnings: tuple[str, ...] = ()
    analysis_results: tuple[AnalysisResult, ...] = ()
    structured_conflicts: tuple[StructuredConflict, ...] = ()


class ResearchEvaluationResult(ContractModel):
    task_completion_rate: float = Field(ge=0, le=1)
    citation_validity_rate: float = Field(ge=0, le=1)
    authorization_violations: int = Field(ge=0)
    average_task_count: float = Field(ge=0)
    average_depth: float = Field(ge=0)
    deterministic: bool
