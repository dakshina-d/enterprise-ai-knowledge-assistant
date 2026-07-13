from uuid import uuid4

import pytest
from enterprise_ai.graph.reducers import MAX_RETAINED_ACTIVITY_EVENTS, append_events
from enterprise_ai.models.events import AgentEvent, AgentEventStatus, AgentEventType

from .test_research_events import _runtime


def _event(sequence: int) -> AgentEvent:
    return AgentEvent(
        event_type=AgentEventType.NODE_COMPLETED,
        sequence_number=sequence,
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        status=AgentEventStatus.COMPLETED,
        public_message="Safe event.",
    )


def test_activity_history_is_bounded_and_evicts_oldest_deterministically() -> None:
    events: tuple[AgentEvent, ...] = ()
    generated = tuple(_event(index) for index in range(MAX_RETAINED_ACTIVITY_EVENTS + 25))
    for item in generated:
        events = append_events(events, (item,))
    assert len(events) == MAX_RETAINED_ACTIVITY_EVENTS
    assert events == generated[-MAX_RETAINED_ACTIVITY_EVENTS:]


def test_new_invocation_reset_is_also_bounded() -> None:
    old = tuple(_event(index) for index in range(10))
    fresh = tuple(_event(index) for index in range(MAX_RETAINED_ACTIVITY_EVENTS + 1))
    assert append_events(old, fresh) == fresh[-MAX_RETAINED_ACTIVITY_EVENTS:]


@pytest.mark.asyncio
async def test_memory_keeps_final_turn_not_research_event_history() -> None:
    runtime, request = _runtime()
    await runtime.ainvoke(request)
    memory = await runtime.inspect_memory(request)
    serialized = repr(memory).casefold()
    assert "research.worker" not in serialized
    assert "activity_events" not in serialized
    assert "planner prompt" not in serialized
    assert "budgetledger" not in serialized
    assert "stack trace" not in serialized
