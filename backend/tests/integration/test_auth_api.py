"""Integration tests for login, bearer authentication, and safe HTTP errors."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from enterprise_ai.core.config import Settings
from enterprise_ai.main import create_app
from enterprise_ai.security.password import PasswordService
from fastapi.testclient import TestClient

SECRET = "integration-signing-secret-with-at-least-32-characters"
PASSWORDS = {
    "demo-viewer": "Viewer-Test-Password",
    "demo-analyst": "Analyst-Test-Password",
    "demo-admin": "Admin-Test-Password",
}


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    password_service = PasswordService()
    settings = Settings(
        app_env="test",
        auth_enabled=True,
        rate_limit_enabled=False,
        auth_token_secret=SECRET,
        auth_token_expiry_minutes=30,
        demo_viewer_password_hash=password_service.hash_password(PASSWORDS["demo-viewer"]),
        demo_analyst_password_hash=password_service.hash_password(PASSWORDS["demo-analyst"]),
        demo_admin_password_hash=password_service.hash_password(PASSWORDS["demo-admin"]),
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("username", "role"),
    [("demo-viewer", "viewer"), ("demo-analyst", "analyst"), ("demo-admin", "administrator")],
)
def test_each_demonstration_user_can_login(client: TestClient, username: str, role: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORDS[username]},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 1800
    assert body["user"]["role"] == role
    assert "password" not in response.text.casefold()
    assert "$argon2" not in response.text
    assert SECRET not in response.text
    current = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert current.status_code == 200
    assert current.json()["role"] == role


def test_unknown_user_and_wrong_password_are_indistinguishable(client: TestClient) -> None:
    unknown = client.post(
        "/api/v1/auth/login",
        json={"username": "unknown-user", "password": "Wrong-Test-Password"},
    )
    wrong = client.post(
        "/api/v1/auth/login",
        json={"username": "demo-viewer", "password": "Wrong-Test-Password"},
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"]
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    for secret in ("Wrong-Test-Password", SECRET, "$argon2", "Traceback"):
        assert secret not in unknown.text
        assert secret not in wrong.text


def test_current_user_requires_and_validates_bearer_token(client: TestClient) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "demo-analyst", "password": PASSWORDS["demo-analyst"]},
    )
    token = login.json()["access_token"]
    current = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert current.status_code == 200
    assert current.json()["role"] == "analyst"
    assert set(current.json()["permissions"]) == {
        "knowledge_search",
        "python_analysis",
        "mcp_tools",
    }

    missing = client.get("/api/v1/auth/me")
    invalid = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.jwt"})
    assert missing.status_code == invalid.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert token not in invalid.text


def test_current_user_rejects_expired_token(client: TestClient) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "demo-viewer", "password": PASSWORDS["demo-viewer"]},
    )
    payload = jwt.decode(login.json()["access_token"], options={"verify_signature": False})
    payload["exp"] = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
    expired_token = jwt.encode(payload, SECRET, algorithm="HS256")

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication.failed"
    assert expired_token not in response.text


@pytest.mark.parametrize("username", [None, "demo-viewer", "demo-analyst", "demo-admin"])
def test_removed_permission_check_route_is_not_reachable(
    client: TestClient, username: str | None
) -> None:
    headers: dict[str, str] = {}
    if username is not None:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": PASSWORDS[username]},
        )
        headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    response = client.get("/api/v1/auth/check-permission/python_analysis", headers=headers)
    assert response.status_code == 404
