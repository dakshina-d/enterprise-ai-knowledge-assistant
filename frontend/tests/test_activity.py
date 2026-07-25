"""Safe activity labels and allowlisted detail projection."""

import pytest
from enterprise_ai.api.schemas import ChatStreamEnvelope
from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.models.events import (
    AgentEvent,
    AgentEventStatus,
    AgentEventType,
    PublicAgentEventPayload,
)
from enterprise_ai.models.graph import Route

from frontend.enterprise_ai_frontend.activity import activity_from_envelope
from frontend.tests.conftest import envelope


def test_known_routes_and_tools_have_friendly_safe_labels(
    graph_output: GraphOutput,
) -> None:
    event = AgentEvent(
        event_type=AgentEventType.MCP_TOOL_SELECTED,
        sequence_number=0,
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
        status=AgentEventStatus.COMPLETED,
        public_message="Selected.",
        payload=PublicAgentEventPayload(
            route=Route.MCP_TOOL,
            mcp_tool_name="get_service_profile",
        ),
    )
    wrapped = ChatStreamEnvelope(
        event_id=event.event_id,
        sequence=1,
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
        event_type=event.event_type.value,
        agent_event=event,
    )
    item = activity_from_envelope(wrapped)
    assert item.label == "Enterprise data tool selected"
    assert item.detail == "Route: mcp_tool · Tool: get_service_profile"
    assert "Selected." not in (item.detail or "")


def test_unknown_event_uses_a_neutral_label(graph_output: GraphOutput) -> None:
    item = activity_from_envelope(
        envelope(
            sequence=0,
            event_type="future.safe_event",
            request_id=graph_output.request_id,
            trace_id=graph_output.trace_id,
            session_id=graph_output.session_id,
        )
    )
    assert item.label == "Agent activity"


def test_fallback_warning_surfaces_only_safe_reason(graph_output: GraphOutput) -> None:
    event = AgentEvent(
        event_type=AgentEventType.RESPONSE_FALLBACK_USED,
        sequence_number=0,
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
        status=AgentEventStatus.WARNING,
        public_message="A safe deterministic response was used.",
        payload=PublicAgentEventPayload(error_code="provider_timeout"),
    )
    wrapped = ChatStreamEnvelope(
        event_id=event.event_id,
        sequence=1,
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
        event_type=event.event_type.value,
        agent_event=event,
    )
    item = activity_from_envelope(wrapped)
    assert item.label == "Safe fallback response used"
    assert item.detail == "Reason: provider_timeout"


def test_failure_handler_completion_has_a_specific_safe_label(
    graph_output: GraphOutput,
) -> None:
    event = AgentEvent(
        event_type=AgentEventType.NODE_COMPLETED,
        sequence_number=0,
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
        node="handle_failure",
        status=AgentEventStatus.COMPLETED,
        public_message="Failure handled safely.",
    )
    wrapped = ChatStreamEnvelope(
        event_id=event.event_id,
        sequence=1,
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
        event_type=event.event_type.value,
        agent_event=event,
    )

    item = activity_from_envelope(wrapped)

    assert item.label == "Failure handled safely"
    assert item.status is AgentEventStatus.COMPLETED


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("mcp.denied", "Enterprise data lookup denied"),
        ("tool.started", "Analysis tool started"),
        ("tool.completed", "Analysis tool completed"),
        ("research.started", "Recursive research started"),
        ("research.round_completed", "Research round completed"),
    ],
)
def test_denied_analysis_and_research_events_are_friendly(
    graph_output: GraphOutput,
    event_type: str,
    expected: str,
) -> None:
    item = activity_from_envelope(
        envelope(
            sequence=0,
            event_type=event_type,
            request_id=graph_output.request_id,
            trace_id=graph_output.trace_id,
            session_id=graph_output.session_id,
        )
    )
    assert item.label == expected
    assert item.detail is None
