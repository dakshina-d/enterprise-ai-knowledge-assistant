"""Safe per-invocation public event construction and custom streaming."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID

from langgraph.config import get_stream_writer

from enterprise_ai.graph.state import GraphState
from enterprise_ai.models.events import (
    AgentEvent,
    AgentEventStatus,
    AgentEventType,
    PublicAgentEventPayload,
)


@dataclass(slots=True)
class EventJournal:
    """Request-correlated events emitted during one guarded node execution."""

    request_id: UUID
    trace_id: UUID
    session_id: UUID
    next_sequence: int
    emitted: list[AgentEvent] = field(default_factory=list)

    def append(self, item: AgentEvent) -> None:
        if (
            item.request_id != self.request_id
            or item.trace_id != self.trace_id
            or item.session_id != self.session_id
            or item.sequence_number != self.next_sequence
        ):
            raise RuntimeError("event journal correlation failed")
        self.emitted.append(item)
        self.next_sequence += 1


_ACTIVE_EVENT_JOURNAL: ContextVar[EventJournal | None] = ContextVar(
    "enterprise_ai_active_event_journal",
    default=None,
)


@contextmanager
def collect_node_events(state: GraphState) -> Iterator[EventJournal]:
    """Collect newly streamed node events in task-local request state."""

    history = state.get("activity_events", ())
    journal = EventJournal(
        request_id=state["request_id"],
        trace_id=state["trace_id"],
        session_id=state["session_id"],
        next_sequence=history[-1].sequence_number + 1 if history else 0,
    )
    token = _ACTIVE_EVENT_JOURNAL.set(journal)
    try:
        yield journal
    finally:
        _ACTIVE_EVENT_JOURNAL.reset(token)


def event(
    state: GraphState,
    event_type: AgentEventType,
    status: AgentEventStatus,
    message: str,
    *,
    node: str | None = None,
    payload: PublicAgentEventPayload | None = None,
) -> AgentEvent:
    journal = _ACTIVE_EVENT_JOURNAL.get()
    history = state.get("activity_events", ())
    sequence_number = (
        journal.next_sequence
        if journal is not None
        else history[-1].sequence_number + 1
        if history
        else 0
    )
    item = AgentEvent(
        event_type=event_type,
        sequence_number=sequence_number,
        request_id=state["request_id"],
        session_id=state["session_id"],
        trace_id=state["trace_id"],
        node=node,
        status=status,
        public_message=message,
        payload=payload or PublicAgentEventPayload(),
    )
    if journal is not None:
        journal.append(item)
    try:
        get_stream_writer()(item.to_public_dict())
    except RuntimeError:
        pass
    return item
