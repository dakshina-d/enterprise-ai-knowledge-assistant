"""Deterministic end-to-end frontend transport/state flows using mocked HTTP streams."""

from collections.abc import Sequence

import httpx
import pytest
from enterprise_ai.api.schemas import ChatStreamEnvelope, PublicAPIError
from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.models.identity import LoginResponse

from frontend.enterprise_ai_frontend.api_client import APIClient
from frontend.enterprise_ai_frontend.config import FrontendSettings
from frontend.enterprise_ai_frontend.errors import FrontendError, SSEProtocolError
from frontend.enterprise_ai_frontend.state import (
    ACCESS_TOKEN,
    MESSAGES,
    USER,
    activity,
    add_user_message,
    authenticate,
    clear_all,
    initialize,
    messages,
)
from frontend.enterprise_ai_frontend.turns import handle_envelope
from frontend.tests.conftest import envelope, frame


def stream_client(events: Sequence[ChatStreamEnvelope]) -> APIClient:
    payload = b"".join(frame(item) for item in events)
    return APIClient(
        FrontendSettings(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=payload,
            )
        ),
    )


@pytest.mark.parametrize(
    "activity_events",
    [
        ("mcp.started", "mcp.tool_selected", "mcp.completed"),
        ("retrieval.started", "retrieval.completed", "citation.validation_completed"),
        ("research.started", "research.round_completed", "research.completed"),
        ("mcp.started", "mcp.denied"),
        ("tool.started", "tool.completed"),
    ],
)
def test_activity_precedes_one_final_answer_for_representative_routes(
    graph_output: GraphOutput,
    activity_events: tuple[str, ...],
) -> None:
    events = [
        envelope(
            sequence=0,
            event_type="stream.started",
            request_id=graph_output.request_id,
            trace_id=graph_output.trace_id,
            session_id=graph_output.session_id,
        ),
        *[
            envelope(
                sequence=index,
                event_type=event_type,
                request_id=graph_output.request_id,
                trace_id=graph_output.trace_id,
                session_id=graph_output.session_id,
            )
            for index, event_type in enumerate(activity_events, start=1)
        ],
        envelope(
            sequence=len(activity_events) + 1,
            event_type="response.completed",
            request_id=graph_output.request_id,
            trace_id=graph_output.trace_id,
            session_id=graph_output.session_id,
            output=graph_output,
        ),
    ]
    state: dict[str, object] = {}
    initialize(state)
    add_user_message(state, "safe fictional query")
    completion_positions: list[int] = []
    for position, item in enumerate(
        stream_client(events).stream_chat(
            access_token="test-token",
            message="safe fictional query",
            session_id=None,
        )
    ):
        _, completed = handle_envelope(state, item, maximum_activity_items=100)
        if completed:
            completion_positions.append(position)

    assert completion_positions == [len(events) - 1]
    assert [item.event_type for item in activity(state)] == [item.event_type for item in events]
    assert [message.role for message in messages(state)] == ["user", "assistant"]


def test_stream_error_after_activity_never_creates_assistant_answer(
    graph_output: GraphOutput,
) -> None:
    failed = envelope(
        sequence=2,
        event_type="stream.error",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
    ).model_copy(
        update={
            "error": PublicAPIError(
                code="dependency.unavailable",
                message="A required service is temporarily unavailable.",
                request_id=graph_output.request_id,
                retryable=True,
            )
        }
    )
    events = (
        envelope(
            sequence=0,
            event_type="stream.started",
            request_id=graph_output.request_id,
            trace_id=graph_output.trace_id,
            session_id=graph_output.session_id,
        ),
        envelope(
            sequence=1,
            event_type="retrieval.started",
            request_id=graph_output.request_id,
            trace_id=graph_output.trace_id,
            session_id=graph_output.session_id,
        ),
        failed,
    )
    state: dict[str, object] = {}
    initialize(state)
    add_user_message(state, "safe fictional query")
    with pytest.raises(FrontendError, match="temporarily unavailable"):
        for item in stream_client(events).stream_chat(
            access_token="test-token",
            message="safe fictional query",
            session_id=None,
        ):
            handle_envelope(state, item, maximum_activity_items=100)

    assert [item.event_type for item in activity(state)] == [
        "stream.started",
        "retrieval.started",
        "stream.error",
    ]
    assert [message.role for message in messages(state)] == ["user"]


def test_interrupted_stream_preserves_activity_without_false_completion(
    graph_output: GraphOutput,
) -> None:
    started = envelope(
        sequence=0,
        event_type="stream.started",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
    )
    state: dict[str, object] = {}
    initialize(state)
    add_user_message(state, "safe fictional query")
    with pytest.raises(SSEProtocolError):
        for item in stream_client((started,)).stream_chat(
            access_token="test-token",
            message="safe fictional query",
            session_id=None,
        ):
            handle_envelope(state, item, maximum_activity_items=100)

    assert len(activity(state)) == 1
    assert [message.role for message in messages(state)] == ["user"]


def test_logout_then_second_login_has_no_cross_user_state(
    login_response: LoginResponse,
) -> None:
    state: dict[str, object] = {}
    initialize(state)
    authenticate(state, login_response)
    add_user_message(state, "first user's message")
    clear_all(state)
    assert state[ACCESS_TOKEN] is None
    assert state[USER] is None
    assert state[MESSAGES] == []
    second_login = login_response.model_copy(
        update={
            "access_token": "second-test-token",
            "user": login_response.user.model_copy(
                update={
                    "username": "demo-viewer-two",
                    "display_name": "Demo Viewer Two",
                }
            ),
        }
    )
    authenticate(state, second_login)
    assert state[ACCESS_TOKEN] == "second-test-token"
    assert state[MESSAGES] == []
