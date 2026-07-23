"""Human-readable projection of public graph events."""

from typing import Literal

from enterprise_ai.api.schemas import ChatStreamEnvelope
from enterprise_ai.models.events import AgentEventStatus

from frontend.enterprise_ai_frontend.models import ActivityItem

LABELS = {
    "stream.started": "Connecting to assistant",
    "request.accepted": "Request accepted",
    "graph.started": "Assistant workflow started",
    "node.started": "Workflow step started",
    "node.completed": "Workflow step completed",
    "node.failed": "Workflow step failed",
    "route.selected": "Supervisor selected a route",
    "retrieval.started": "Knowledge retrieval started",
    "retrieval.completed": "Knowledge retrieval completed",
    "tool.authorization_started": "Tool authorization started",
    "tool.authorized": "Tool authorized",
    "tool.denied": "Tool denied",
    "research.started": "Recursive research started",
    "research.batch_started": "Research batch started",
    "research.batch_completed": "Research batch completed",
    "research.catalog_completed": "Research catalog prepared",
    "research.planning_started": "Research planning started",
    "research.plan_created": "Research plan created",
    "research.plan_validated": "Research plan validated",
    "research.worker_dispatched": "Research worker dispatched",
    "research.worker_started": "Research worker started",
    "research.retrieval_completed": "Research retrieval completed",
    "research.analysis_completed": "Research analysis completed",
    "research.worker_completed": "Research worker completed",
    "research.worker_failed": "Research worker failed",
    "research.round_completed": "Research round completed",
    "research.coverage_assessed": "Research coverage assessed",
    "research.child_tasks_created": "Follow-up research tasks created",
    "research.aggregation_completed": "Research evidence aggregated",
    "research.partial": "Research completed with gaps",
    "research.budget_exhausted": "Research budget exhausted",
    "research.completed": "Recursive research completed",
    "research.failed": "Recursive research failed",
    "mcp.started": "Enterprise data lookup started",
    "mcp.tool_selected": "Enterprise data tool selected",
    "mcp.completed": "Enterprise data lookup completed",
    "mcp.denied": "Enterprise data lookup denied",
    "mcp.failed": "Enterprise data lookup failed",
    "tool.started": "Analysis tool started",
    "tool.completed": "Analysis tool completed",
    "tool.failed": "Analysis tool failed",
    "response.generation_started": "Response generation started",
    "response.generation_completed": "Response generation completed",
    "response.generation_failed": "Response generation failed",
    "citation.validation_started": "Citation validation started",
    "citation.validation_completed": "Citation validation completed",
    "citation.validation_failed": "Citation validation failed",
    "response.repair_started": "Response repair started",
    "response.repair_completed": "Response repair completed",
    "response.fallback_used": "Safe fallback response used",
    "validation.completed": "Evidence validation completed",
    "memory.load_started": "Conversation context loading",
    "memory.loaded": "Conversation context loaded",
    "memory.context_resolved": "Conversation context resolved",
    "memory.update_started": "Conversation memory update started",
    "memory.updated": "Conversation memory updated",
    "memory.evicted": "Older conversation context evicted",
    "memory.failed": "Conversation memory unavailable",
    "response.completed": "Response completed",
    "response.failed": "Response failed",
    "stream.error": "Activity stream failed",
}


def activity_from_envelope(envelope: ChatStreamEnvelope) -> ActivityItem:
    event = envelope.agent_event
    status: AgentEventStatus | Literal["started", "failed", "completed"] = "started"
    detail: str | None = None
    if event is not None:
        status = event.status
        payload = event.payload
        values = (
            ("Route", payload.route.value if payload.route else None),
            (
                "Tool",
                payload.mcp_tool_name or (payload.tool_name.value if payload.tool_name else None),
            ),
            ("Results", payload.result_count),
            ("Evidence", payload.evidence_count),
            ("Round", payload.round_number),
        )
        detail = " · ".join(f"{label}: {value}" for label, value in values if value is not None)
    elif envelope.event_type in {"response.failed", "stream.error"}:
        status = "failed"
    elif envelope.event_type == "response.completed":
        status = "completed"
    return ActivityItem(
        event_id=envelope.event_id,
        sequence=envelope.sequence,
        timestamp=envelope.timestamp,
        event_type=envelope.event_type,
        label=LABELS.get(envelope.event_type, "Agent activity"),
        status=status,
        detail=detail or None,
    )
