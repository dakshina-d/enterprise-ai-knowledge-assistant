"""Native SSE chat delivery integration tests."""

import json

from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.main import create_app
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.exceptions import RetrievalValidationError
from enterprise_ai.retrieval.hybrid.models import HybridRetrievalResult
from fastapi.testclient import TestClient

from backend.tests.integration.chat_api_support import (
    FakeGraphRuntime,
    authorization_header,
    chat_settings,
    runtime_factory,
)


def _events(text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        lines = block.splitlines()
        if not lines or lines[0].startswith(":"):
            continue
        event = next(line[7:] for line in lines if line.startswith("event: "))
        identifier = next(line[4:] for line in lines if line.startswith("id: "))
        data = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
        events.append({"event": event, "id": identifier, "data": data})
    return events


def test_sse_stream_has_one_execution_and_one_terminal_final_output() -> None:
    runtime = FakeGraphRuntime()
    with TestClient(
        create_app(chat_settings(), runtime_factory=runtime_factory(runtime))
    ) as client:
        response = client.post(
            "/api/v1/chat/stream",
            headers=authorization_header(client),
            json={"message": "hello"},
        )

    events = _events(response.text)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert "content-length" not in response.headers
    assert [item["event"] for item in events] == [
        "stream.started",
        "request.accepted",
        "response.completed",
    ]
    assert [item["data"]["sequence"] for item in events] == [0, 1, 2]
    assert len({item["id"] for item in events}) == len(events)
    assert "response" in events[-1]["data"]
    assert len(runtime.stream_inputs) == 1
    assert runtime.inputs == []


def test_sse_failure_emits_one_safe_terminal_error() -> None:
    runtime = FakeGraphRuntime()
    runtime.failure = RuntimeError("private dependency detail")
    with TestClient(
        create_app(chat_settings(), runtime_factory=runtime_factory(runtime))
    ) as client:
        response = client.post(
            "/api/v1/chat/stream",
            headers=authorization_header(client),
            json={"message": "hello"},
        )

    events = _events(response.text)
    assert [item["event"] for item in events] == ["stream.started", "stream.error"]
    assert events[-1]["data"]["error"]["code"] == "internal.unexpected"
    assert "private dependency detail" not in response.text


class FailingRetriever:
    async def retrieve(self, *args: object, **kwargs: object) -> HybridRetrievalResult:
        raise RetrievalValidationError("private missing retrieval artifact path")


def test_native_retrieval_failure_matches_json_safe_graph_outcome() -> None:
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
    ) as client:
        headers = authorization_header(client, "demo-viewer")
        streamed = client.post(
            "/api/v1/chat/stream",
            headers=headers,
            json={"message": "Find the active recovery runbook."},
        )
        ordinary = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "Find the active recovery runbook."},
        )

    events = _events(streamed.text)
    terminal = events[-1]
    output = terminal["data"]["response"]
    activity = [
        item["data"].get("agent_event")
        for item in events
        if item["data"].get("agent_event") is not None
    ]

    assert streamed.status_code == ordinary.status_code == 200
    assert terminal["event"] == "response.failed"
    assert output["selected_route"] == "failure"
    assert output["completion_status"] == "failed"
    assert output["response_text"] == "The request failed safely."
    assert output["evidence"] == output["citations"] == []
    assert any(item["event_type"] == "route.selected" for item in activity)
    assert any(item["event_type"] == "retrieval.started" for item in activity)
    assert any(
        item["event_type"] == "node.completed"
        and item["node"] == "handle_failure"
        and item["public_message"] == "Failure handled safely."
        for item in activity
    )
    assert sum(item["event_type"] == "response.failed" for item in activity) == 1
    ordinary_output = ordinary.json()
    for field in (
        "selected_route",
        "completion_status",
        "response_text",
        "evidence",
        "citations",
    ):
        assert ordinary_output[field] == output[field]
    assert "private missing retrieval artifact path" not in streamed.text
