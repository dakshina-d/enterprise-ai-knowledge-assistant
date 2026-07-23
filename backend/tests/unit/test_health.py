"""Unit tests for the health API contract."""

from enterprise_ai.main import create_app
from fastapi.testclient import TestClient


def test_live_health_endpoint() -> None:
    """The liveness endpoint reports a running process."""
    with TestClient(create_app()) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_ready_health_endpoint() -> None:
    """The readiness endpoint reports placeholder readiness."""
    with TestClient(create_app()) as client:
        response = client.get("/health/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


def test_protected_chat_is_documented_but_unavailable_without_auth_configuration() -> None:
    application = create_app()
    assert "/api/v1/chat" in application.openapi()["paths"]
    assert "/api/v1/chat/stream" in application.openapi()["paths"]
    with TestClient(application) as client:
        response = client.post("/api/v1/chat", json={"message": "hello"})
    assert response.status_code == 401
