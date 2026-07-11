"""Safe per-invocation public event construction and custom streaming."""

from langgraph.config import get_stream_writer

from enterprise_ai.graph.state import GraphState
from enterprise_ai.models.events import (
    AgentEvent,
    AgentEventStatus,
    AgentEventType,
    PublicAgentEventPayload,
)


def event(
    state: GraphState,
    event_type: AgentEventType,
    status: AgentEventStatus,
    message: str,
    *,
    node: str | None = None,
    payload: PublicAgentEventPayload | None = None,
) -> AgentEvent:
    item = AgentEvent(
        event_type=event_type,
        sequence_number=len(state.get("activity_events", ())),
        request_id=state["request_id"],
        session_id=state["session_id"],
        trace_id=state["trace_id"],
        node=node,
        status=status,
        public_message=message,
        payload=payload or PublicAgentEventPayload(),
    )
    try:
        get_stream_writer()(item.to_public_dict())
    except RuntimeError:
        pass
    return item
