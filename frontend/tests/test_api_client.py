"""HTTP request safety, error mapping, and response cleanup tests."""

import json
from collections.abc import Iterator

import httpx
import pytest
from enterprise_ai.graph.schemas import GraphOutput

from frontend.enterprise_ai_frontend.api_client import APIClient
from frontend.enterprise_ai_frontend.config import FrontendSettings
from frontend.enterprise_ai_frontend.errors import (
    AuthenticationExpiredError,
    FrontendError,
    SSEProtocolError,
)
from frontend.tests.conftest import envelope, frame


class ObservedStream(httpx.SyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self.chunks

    def close(self) -> None:
        self.closed = True


def test_login_validates_response_without_exposing_password() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "access_token": "test-token",
                "token_type": "Bearer",
                "expires_in": 1800,
                "user": {
                    "user_id": "c450d151-35a2-47e9-9a17-725eb50c66ba",
                    "username": "demo-analyst",
                    "display_name": "Demo Analyst",
                    "role": "analyst",
                },
                "permissions": ["knowledge_search", "python_analysis", "mcp_tools"],
                "expires_at": "2030-01-01T00:00:00Z",
            },
        )

    client = APIClient(FrontendSettings(), transport=httpx.MockTransport(handler))
    result = client.login("demo-analyst", "temporary-password")
    assert result.access_token == "test-token"
    assert seen == {"username": "demo-analyst", "password": "temporary-password"}
    assert "temporary-password" not in repr(result)


def test_login_maps_unavailable_and_malformed_responses() -> None:
    unavailable = APIClient(
        FrontendSettings(),
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("private", request=request))
        ),
    )
    with pytest.raises(FrontendError, match="unavailable"):
        unavailable.login("user", "password-value")
    malformed = APIClient(
        FrontendSettings(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"token": "bad"})),
    )
    with pytest.raises(SSEProtocolError, match="authentication response"):
        malformed.login("user", "password-value")

    rejected = APIClient(
        FrontendSettings(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(401, json={})),
    )
    with pytest.raises(FrontendError, match="username or password") as caught:
        rejected.login("user", "password-value")
    assert caught.value.code == "authentication.failed"


def test_stream_chat_sends_only_documented_fields_and_closes_response(
    graph_output: GraphOutput,
) -> None:
    started = envelope(
        sequence=0,
        event_type="stream.started",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
    )
    completed = envelope(
        sequence=1,
        event_type="response.completed",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
        output=graph_output,
    )
    observed = ObservedStream((frame(started)[:17], frame(started)[17:], frame(completed)))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat/stream"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["Accept"] == "text/event-stream"
        assert json.loads(request.content) == {
            "message": "hello",
            "session_id": str(graph_output.session_id),
        }
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=observed,
        )

    client = APIClient(FrontendSettings(), transport=httpx.MockTransport(handler))
    events = list(
        client.stream_chat(
            access_token="test-token",
            message="hello",
            session_id=graph_output.session_id,
        )
    )
    assert [event.event_type for event in events] == [
        "stream.started",
        "response.completed",
    ]
    assert observed.closed


def test_http_failures_and_interrupted_stream_are_safe() -> None:
    limited = APIClient(
        FrontendSettings(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                429,
                headers={"Retry-After": "12"},
                json={
                    "error": {
                        "code": "rate_limit.exceeded",
                        "message": "Too many requests.",
                        "request_id": "b4879513-2db0-4463-8d89-93ca9792d688",
                        "retryable": True,
                    }
                },
            )
        ),
    )
    with pytest.raises(FrontendError) as caught:
        list(limited.stream_chat(access_token="token", message="hello", session_id=None))
    assert caught.value.retry_after_seconds == 12
    assert caught.value.code == "rate_limit.exceeded"

    expired = APIClient(
        FrontendSettings(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(401, json={})),
    )
    with pytest.raises(AuthenticationExpiredError):
        list(expired.stream_chat(access_token="rejected", message="hello", session_id=None))

    incomplete = ObservedStream((b"event: stream.started\n",))
    interrupted = APIClient(
        FrontendSettings(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=incomplete,
            )
        ),
    )
    with pytest.raises(SSEProtocolError):
        list(interrupted.stream_chat(access_token="token", message="hello", session_id=None))
    assert incomplete.closed


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (400, "invalid"),
        (409, "cannot be continued"),
        (422, "could not be accepted"),
        (500, "safely"),
        (503, "temporarily unavailable"),
        (504, "timed out"),
    ],
)
def test_documented_http_failures_have_bounded_default_messages(
    status_code: int,
    message: str,
) -> None:
    client = APIClient(
        FrontendSettings(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, content=b"not-json-private-body")
        ),
    )
    with pytest.raises(FrontendError, match=message) as caught:
        list(client.stream_chat(access_token="token", message="hello", session_id=None))
    assert "private-body" not in caught.value.public_message
