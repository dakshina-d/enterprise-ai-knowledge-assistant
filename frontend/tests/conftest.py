"""Shared public-contract fixtures for frontend tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from enterprise_ai.api.schemas import ChatStreamEnvelope
from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import (
    AgentEvent,
    AgentEventStatus,
    AgentEventType,
)
from enterprise_ai.models.graph import Intent, PublicAgentStatus, Route
from enterprise_ai.models.identity import (
    LoginResponse,
    PublicUserProfile,
    ToolPermission,
    UserRole,
)


@pytest.fixture
def graph_output() -> GraphOutput:
    request_id = uuid4()
    return GraphOutput(
        graph_version="1.2",
        request_id=request_id,
        trace_id=uuid4(),
        session_id=uuid4(),
        completion_status=ProcessingStatus.COMPLETED,
        selected_route=Route.DIRECT_RESPONSE,
        intent=Intent.CONVERSATIONAL,
        response_text="Safe fictional answer.",
        agent_status=PublicAgentStatus(
            request_id=request_id,
            status=ProcessingStatus.COMPLETED,
            public_message="Completed.",
            route=Route.DIRECT_RESPONSE,
        ),
    )


@pytest.fixture
def login_response() -> LoginResponse:
    now = datetime.now(UTC)
    return LoginResponse(
        access_token="test-token-value",
        expires_in=1_800,
        user=PublicUserProfile(
            user_id=uuid4(),
            username="demo-analyst",
            display_name="Demo Analyst",
            role=UserRole.ANALYST,
        ),
        permissions=frozenset(
            {
                ToolPermission.KNOWLEDGE_SEARCH,
                ToolPermission.PYTHON_ANALYSIS,
                ToolPermission.MCP_TOOLS,
            }
        ),
        expires_at=now + timedelta(minutes=30),
    )


def envelope(
    *,
    sequence: int,
    event_type: str,
    request_id: UUID,
    trace_id: UUID,
    session_id: UUID,
    output: GraphOutput | None = None,
) -> ChatStreamEnvelope:
    agent_event = None
    if event_type == "request.accepted":
        agent_event = AgentEvent(
            event_type=AgentEventType.REQUEST_ACCEPTED,
            sequence_number=0,
            request_id=request_id,
            trace_id=trace_id,
            session_id=session_id,
            status=AgentEventStatus.ACCEPTED,
            public_message="Accepted.",
        )
    return ChatStreamEnvelope(
        event_id=uuid4(),
        sequence=sequence,
        request_id=request_id,
        trace_id=trace_id,
        session_id=session_id,
        event_type=event_type,
        agent_event=agent_event,
        response=output,
    )


def frame(item: ChatStreamEnvelope) -> bytes:
    return (
        f"id: {item.event_id}\r\n"
        f"event: {item.event_type}\r\n"
        f"data: {item.model_dump_json(exclude_none=True)}\r\n\r\n"
    ).encode()
