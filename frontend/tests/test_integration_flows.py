"""Deterministic end-to-end frontend transport/state flows using mocked HTTP streams."""

from collections.abc import Sequence
from pathlib import Path
from typing import cast

import httpx
import pytest
from enterprise_ai.api.schemas import ChatStreamEnvelope, PublicAPIError
from enterprise_ai.core.config import Settings
from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.main import create_app
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.graph import Route
from enterprise_ai.models.identity import LoginResponse, UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.exceptions import RetrievalValidationError
from enterprise_ai.retrieval.hybrid.models import HybridRetrievalResult
from enterprise_ai.security.password import PasswordService
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from streamlit.testing.v1 import AppTest

from frontend.enterprise_ai_frontend.api_client import APIClient
from frontend.enterprise_ai_frontend.config import FrontendSettings
from frontend.enterprise_ai_frontend.errors import FrontendError, SSEProtocolError
from frontend.enterprise_ai_frontend.models import FrontendUser
from frontend.enterprise_ai_frontend.state import (
    ACCESS_TOKEN,
    ACTIVITY,
    LAST_ERROR,
    LAST_RESPONSE,
    MESSAGES,
    PENDING,
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

APP_PATH = Path("frontend/streamlit_app.py")
CHAT_SECRET = "frontend-integration-secret-with-at-least-48-characters"
CHAT_PASSWORD = "Frontend-Integration-Test-Password"


def chat_settings() -> Settings:
    password_hash = PasswordService().hash_password(CHAT_PASSWORD)
    return Settings(
        app_env="test",
        auth_enabled=True,
        auth_token_secret=SecretStr(CHAT_SECRET),
        demo_viewer_password_hash=SecretStr(password_hash),
        demo_analyst_password_hash=SecretStr(password_hash),
        demo_admin_password_hash=SecretStr(password_hash),
        rate_limit_enabled=False,
    )


def authorization_header(client: TestClient) -> dict[str, str]:
    app = cast(FastAPI, client.app)
    profile = app.state.authentication_service.authenticate(
        "demo-viewer",
        SecretStr(CHAT_PASSWORD),
    )
    token_value = app.state.token_service.issue_token(
        profile,
        app.state.authorization_service.permissions_for_role(profile.role),
    )
    return {"Authorization": f"Bearer {token_value}"}


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
    state[PENDING] = True
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
    assert state[PENDING] is False
    assert state[LAST_ERROR] == "A required service is temporarily unavailable."
    assert state[LAST_RESPONSE] is None


def test_valid_response_failed_commits_one_failed_assistant_turn(
    graph_output: GraphOutput,
) -> None:
    failed_output = graph_output.model_copy(
        update={
            "completion_status": ProcessingStatus.FAILED,
            "selected_route": Route.FAILURE,
            "response_text": "The request failed safely.",
            "citations": (),
            "evidence": (),
        }
    )
    terminal = envelope(
        sequence=2,
        event_type="response.failed",
        request_id=failed_output.request_id,
        trace_id=failed_output.trace_id,
        session_id=failed_output.session_id,
        output=failed_output,
    )
    events = (
        envelope(
            sequence=0,
            event_type="stream.started",
            request_id=failed_output.request_id,
            trace_id=failed_output.trace_id,
            session_id=failed_output.session_id,
        ),
        envelope(
            sequence=1,
            event_type="retrieval.started",
            request_id=failed_output.request_id,
            trace_id=failed_output.trace_id,
            session_id=failed_output.session_id,
        ),
        terminal,
    )
    state: dict[str, object] = {}
    initialize(state)
    add_user_message(state, "safe fictional query")
    state[PENDING] = True
    completed = []

    for item in stream_client(events).stream_chat(
        access_token="test-token",
        message="safe fictional query",
        session_id=None,
    ):
        _, is_terminal = handle_envelope(state, item, maximum_activity_items=100)
        completed.append(is_terminal)

    assistant = messages(state)[-1]
    assert completed == [False, False, True]
    assert assistant.role == "assistant"
    assert assistant.content == "The request failed safely."
    assert assistant.completion_status is ProcessingStatus.FAILED
    assert assistant.selected_route is Route.FAILURE
    assert assistant.request_id == failed_output.request_id
    assert assistant.citations == ()
    assert state[PENDING] is False
    assert state[LAST_RESPONSE] == failed_output
    assert [item.event_type for item in activity(state)].count("response.failed") == 1


def test_response_failed_without_output_is_a_safe_protocol_error(
    graph_output: GraphOutput,
) -> None:
    malformed = envelope(
        sequence=0,
        event_type="response.failed",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
    )
    state: dict[str, object] = {}
    initialize(state)

    with pytest.raises(SSEProtocolError, match="did not contain a final response"):
        handle_envelope(state, malformed, maximum_activity_items=100)

    assert messages(state) == []
    assert [item.event_type for item in activity(state)] == ["response.failed"]


class FailingRetriever:
    async def retrieve(self, *args: object, **kwargs: object) -> HybridRetrievalResult:
        raise RetrievalValidationError("private missing retrieval artifact path")


def test_native_retrieval_failure_is_received_stored_and_rendered_safely() -> None:
    retrieval_settings = RetrievalSettings()
    runtime = GraphRuntime(
        build_graph(
            retrieval_settings,
            FailingRetriever(),
            checkpointer=create_checkpointer(),
        ),
        retrieval_settings,
    )
    with TestClient(
        create_app(chat_settings(), runtime_factory=lambda _settings: runtime)
    ) as backend:
        response = backend.post(
            "/api/v1/chat/stream",
            headers=authorization_header(backend),
            json={"message": "Find the active recovery runbook."},
        )

    client = APIClient(
        FrontendSettings(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=response.content,
            )
        ),
    )
    state: dict[str, object] = {}
    initialize(state)
    add_user_message(state, "Find the active recovery runbook.")
    state[PENDING] = True
    for item in client.stream_chat(
        access_token="test-token",
        message="Find the active recovery runbook.",
        session_id=None,
    ):
        handle_envelope(state, item, maximum_activity_items=100)

    assistant = messages(state)[-1]
    timeline = activity(state)
    assert assistant.content == "The request failed safely."
    assert assistant.completion_status is ProcessingStatus.FAILED
    assert assistant.selected_route is Route.FAILURE
    assert assistant.citations == ()
    assert state[PENDING] is False
    assert [item.event_type for item in timeline].count("response.failed") == 1
    assert any(item.detail == "Route: simple_retrieval" for item in timeline)
    assert any(item.label == "Knowledge retrieval started" for item in timeline)
    assert any(item.label == "Failure handled safely" for item in timeline)
    assert timeline[-1].label == "Response failed"

    app = AppTest.from_file(str(APP_PATH))
    app.session_state[ACCESS_TOKEN] = "in-memory-test-token"
    app.session_state[USER] = FrontendUser(
        username="demo-viewer",
        display_name="Demo Viewer",
        role=UserRole.VIEWER,
    )
    app.session_state[MESSAGES] = messages(state)
    app.session_state[ACTIVITY] = timeline
    app.run()
    visible = "\n".join(
        str(element.value) for collection in (app.markdown, app.caption) for element in collection
    )

    assert "The request failed safely." in visible
    assert "Completion: failed" in visible
    assert "Route: failure" in visible
    assert "No document citations were provided." in visible
    assert "Route: simple_retrieval" in visible
    assert "Knowledge retrieval started" in visible
    assert "Failure handled safely" in visible
    assert "Response failed" in visible
    assert "private missing retrieval artifact path" not in visible


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
