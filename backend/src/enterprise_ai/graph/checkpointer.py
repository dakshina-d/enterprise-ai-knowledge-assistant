"""Checkpoint construction kept separate from graph topology."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.llm.models import (
    CitationValidationResult,
    Confidence,
    GroundedAnswerDraft,
    GroundedResponse,
    ResponseMode,
)
from enterprise_ai.mcp_tools.models import (
    BusinessCriticality,
    ChangeStatus,
    LifecycleStatus,
    MCPExecutionResult,
    MetricPeriod,
    ServiceTier,
)
from enterprise_ai.memory.models import MemoryContext
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import AgentEvent, AgentEventStatus, AgentEventType
from enterprise_ai.models.graph import (
    GraphError,
    Intent,
    Route,
    ValidationReport,
    ValidationResult,
)
from enterprise_ai.models.identity import (
    AccessLevel,
    AuthenticatedPrincipal,
    ToolPermission,
    UserRole,
)
from enterprise_ai.models.retrieval import DocumentType
from enterprise_ai.models.tools import ToolExecutionStatus, ToolName
from enterprise_ai.research.models import (
    CoverageStatus,
    ResearchResult,
    ResearchTaskStatus,
    ResearchTaskType,
)
from enterprise_ai.research.structured_conflicts import (
    StructuredConflictKind,
    StructuredFactType,
)
from enterprise_ai.retrieval.filters import DenseQueryFilters
from enterprise_ai.retrieval.hybrid.models import CompletionStatus, HybridEvidence
from enterprise_ai.retrieval.identifiers import EnterpriseIdentifier, EnterpriseIdentifierKind
from enterprise_ai.tools.python_analysis.models import (
    AnalysisOperation,
    AnalysisRequest,
    AnalysisResult,
    DateInterval,
)

CHECKPOINT_ALLOWED_TYPES = (
    AccessLevel,
    AgentEvent,
    AgentEventStatus,
    AgentEventType,
    AnalysisOperation,
    AnalysisRequest,
    AnalysisResult,
    AuthenticatedPrincipal,
    BusinessCriticality,
    ChangeStatus,
    CitationValidationResult,
    CompletionStatus,
    Confidence,
    CoverageStatus,
    DateInterval,
    DenseQueryFilters,
    DocumentType,
    EnterpriseIdentifier,
    EnterpriseIdentifierKind,
    GraphError,
    GraphOutput,
    GroundedAnswerDraft,
    GroundedResponse,
    HybridEvidence,
    Intent,
    LifecycleStatus,
    MCPExecutionResult,
    MemoryContext,
    MetricPeriod,
    ProcessingStatus,
    ResearchResult,
    ResearchTaskStatus,
    ResearchTaskType,
    ResponseMode,
    Route,
    ServiceTier,
    StructuredConflictKind,
    StructuredFactType,
    ToolExecutionStatus,
    ToolName,
    ToolPermission,
    UserRole,
    ValidationReport,
    ValidationResult,
)


def create_checkpointer() -> InMemorySaver:
    """Return the explicit local-development checkpoint implementation."""
    serializer = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_ALLOWED_TYPES)
    return InMemorySaver(serde=serializer)
