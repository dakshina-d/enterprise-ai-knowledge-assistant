"""Native SSE chat delivery integration tests."""

import json

from enterprise_ai.main import create_app
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
