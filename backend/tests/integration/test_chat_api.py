"""Authenticated JSON chat endpoint integration tests."""

from uuid import uuid4

from enterprise_ai.graph.runtime import SessionOwnershipError
from enterprise_ai.main import create_app
from fastapi.testclient import TestClient

from backend.tests.integration.chat_api_support import (
    FakeGraphRuntime,
    authorization_header,
    chat_settings,
    runtime_factory,
)


def test_json_chat_uses_one_shared_runtime_and_server_owned_identity() -> None:
    runtime = FakeGraphRuntime()
    app = create_app(chat_settings(), runtime_factory=runtime_factory(runtime))
    with TestClient(app) as client:
        headers = authorization_header(client)
        first = client.post("/api/v1/chat", headers=headers, json={"message": "hello"})
        session_id = first.json()["session_id"]
        second = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "continue", "session_id": session_id, "top_k": 7},
        )

    assert first.status_code == second.status_code == 200
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert first.headers["Referrer-Policy"] == "no-referrer"
    assert first.json()["request_id"] == first.headers["X-Request-ID"]
    assert runtime.inputs[0].principal.identity.username == "demo-analyst"
    assert runtime.inputs[1].session_id == runtime.inputs[0].session_id
    assert runtime.inputs[1].requested_top_k == 7
    assert runtime.closed == 1


def test_json_chat_requires_authentication_and_rejects_owned_fields() -> None:
    runtime = FakeGraphRuntime()
    with TestClient(
        create_app(chat_settings(), runtime_factory=runtime_factory(runtime))
    ) as client:
        missing = client.post("/api/v1/chat", json={"message": "hello"})
        injected = client.post(
            "/api/v1/chat",
            headers=authorization_header(client),
            json={"message": "hello", "role": "administrator"},
        )

    assert missing.status_code == 401
    assert injected.status_code == 422
    assert runtime.inputs == []


def test_unknown_api_route_uses_the_safe_error_contract() -> None:
    runtime = FakeGraphRuntime()
    with TestClient(
        create_app(chat_settings(), runtime_factory=runtime_factory(runtime))
    ) as client:
        response = client.get("/api/v1/unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource.not_found"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_json_chat_translates_session_conflict_without_internal_detail() -> None:
    runtime = FakeGraphRuntime()
    runtime.failure = SessionOwnershipError("private owner detail")
    with TestClient(
        create_app(chat_settings(), runtime_factory=runtime_factory(runtime))
    ) as client:
        response = client.post(
            "/api/v1/chat",
            headers=authorization_header(client),
            json={"message": "hello", "session_id": str(uuid4())},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session.ownership_conflict"
    assert "private owner detail" not in response.text


def test_json_and_streaming_endpoints_share_the_authenticated_user_quota() -> None:
    runtime = FakeGraphRuntime()
    settings = chat_settings(
        rate_limit_enabled=True,
        rate_limit_standard_capacity=1,
        rate_limit_standard_refill_per_second=0.001,
    )
    with TestClient(create_app(settings, runtime_factory=runtime_factory(runtime))) as client:
        headers = authorization_header(client)
        allowed = client.post("/api/v1/chat", headers=headers, json={"message": "hello"})
        denied = client.post(
            "/api/v1/chat/stream",
            headers=headers,
            json={"message": "hello"},
        )

    assert allowed.status_code == 200
    assert denied.status_code == 429
    assert int(denied.headers["Retry-After"]) > 0
    assert len(runtime.inputs) == 1
    assert runtime.stream_inputs == []


def test_json_chat_runs_a_bounded_real_graph_turn_offline() -> None:
    with TestClient(create_app(chat_settings())) as client:
        direct = client.post(
            "/api/v1/chat",
            headers=authorization_header(client),
            json={"message": "hello"},
        )
        analyst_mcp = client.post(
            "/api/v1/chat",
            headers=authorization_header(client),
            json={"message": "Who owns the payment-gateway service?"},
        )
        viewer_mcp = client.post(
            "/api/v1/chat",
            headers=authorization_header(client, "demo-viewer"),
            json={"message": "Who owns the payment-gateway service?"},
        )

    assert direct.status_code == analyst_mcp.status_code == viewer_mcp.status_code == 200
    assert direct.json()["selected_route"] == "direct_response"
    assert analyst_mcp.json()["selected_route"] == "mcp_tool"
    assert analyst_mcp.json()["mcp_provenance"]["record_identifier"] == "payment-gateway"
    assert viewer_mcp.json()["selected_route"] == "deny"
    assert viewer_mcp.json()["completion_status"] == "denied"


def test_real_runtime_rejects_cross_user_session_reuse() -> None:
    with TestClient(create_app(chat_settings())) as client:
        analyst = client.post(
            "/api/v1/chat",
            headers=authorization_header(client),
            json={"message": "hello"},
        )
        conflict = client.post(
            "/api/v1/chat",
            headers=authorization_header(client, "demo-viewer"),
            json={"message": "hello", "session_id": analyst.json()["session_id"]},
        )

    assert analyst.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "session.ownership_conflict"
