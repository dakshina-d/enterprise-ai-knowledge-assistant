"""Integration tests for login and authenticated-user rate limiting."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from enterprise_ai.core.config import Settings
from enterprise_ai.main import create_app
from enterprise_ai.rate_limit.clock import ManualClock
from enterprise_ai.rate_limit.policy import policies_from_settings
from enterprise_ai.rate_limit.store import RateLimitStoreError
from enterprise_ai.rate_limit.token_bucket import TokenBucketRateLimiter
from enterprise_ai.security.password import PasswordService
from fastapi.testclient import TestClient

SECRET = "rate-limit-integration-secret-with-at-least-48-characters"
PASSWORDS = {
    "demo-viewer": "Viewer-Rate-Test-Password",
    "demo-analyst": "Analyst-Rate-Test-Password",
    "demo-admin": "Admin-Rate-Test-Password",
}


@lru_cache
def _hashes() -> tuple[str, str, str]:
    service = PasswordService()
    return tuple(service.hash_password(value) for value in PASSWORDS.values())  # type: ignore[return-value]


def _settings(
    *,
    enabled: bool = True,
    login_capacity: float = 2,
    standard_capacity: float = 2,
    trust_proxy: bool = False,
) -> Settings:
    viewer_hash, analyst_hash, admin_hash = _hashes()
    return Settings(
        app_env="test",
        auth_enabled=True,
        auth_token_secret=SECRET,
        demo_viewer_password_hash=viewer_hash,
        demo_analyst_password_hash=analyst_hash,
        demo_admin_password_hash=admin_hash,
        rate_limit_enabled=enabled,
        rate_limit_login_capacity=login_capacity,
        rate_limit_login_refill_per_second=0.001,
        rate_limit_standard_capacity=standard_capacity,
        rate_limit_standard_refill_per_second=0.001,
        trust_proxy_headers=trust_proxy,
        trusted_proxy_hosts="testclient" if trust_proxy else "",
    )


@contextmanager
def _client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


def _login(client: TestClient, username: str = "demo-viewer") -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORDS[username]},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_login_requests_within_capacity_reach_authentication_then_return_429() -> None:
    with _client(_settings(login_capacity=2)) as client:
        for username in ("unknown-one", "unknown-two"):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": "Invalid-Test-Password"},
            )
            assert response.status_code == 401
        denied = client.post(
            "/api/v1/auth/login",
            json={"username": "unknown-three", "password": "Invalid-Test-Password"},
        )

    assert denied.status_code == 429
    assert int(denied.headers["Retry-After"]) > 0
    assert denied.headers["X-RateLimit-Limit"] == "2"
    assert denied.headers["X-RateLimit-Remaining"] == "0"
    assert denied.json()["error"]["code"] == "rate_limit.exceeded"
    assert denied.json()["error"]["retryable"] is True
    for forbidden in ("Invalid-Test-Password", "$argon2", "anonymous:", "testclient", "Traceback"):
        assert forbidden not in denied.text


def test_valid_and_invalid_logins_consume_same_anonymous_policy() -> None:
    with _client(_settings(login_capacity=1)) as client:
        assert _login(client)
        denied = client.post(
            "/api/v1/auth/login",
            json={"username": "unknown", "password": "Invalid-Test-Password"},
        )
    assert denied.status_code == 429


def test_known_and_unknown_usernames_have_identical_limit_sequence() -> None:
    statuses: list[list[int]] = []
    for username in ("demo-viewer", "unknown-user"):
        with _client(_settings(login_capacity=2)) as client:
            attempts = [
                client.post(
                    "/api/v1/auth/login",
                    json={"username": username, "password": "Invalid-Test-Password"},
                ).status_code
                for _ in range(3)
            ]
            statuses.append(attempts)
    assert statuses == [[401, 401, 429], [401, 401, 429]]


def test_untrusted_forwarded_header_cannot_bypass_login_bucket() -> None:
    with _client(_settings(login_capacity=1)) as client:
        first = client.post(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": "198.51.100.1"},
            json={"username": "unknown", "password": "Invalid-Test-Password"},
        )
        second = client.post(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": "198.51.100.2"},
            json={"username": "unknown", "password": "Invalid-Test-Password"},
        )
    assert first.status_code == 401
    assert second.status_code == 429


def test_authenticated_users_have_independent_buckets() -> None:
    with _client(_settings(login_capacity=10, standard_capacity=2)) as client:
        viewer = _login(client, "demo-viewer")
        analyst = _login(client, "demo-analyst")
        viewer_headers = {"Authorization": f"Bearer {viewer}"}
        analyst_headers = {"Authorization": f"Bearer {analyst}"}
        assert client.get("/api/v1/auth/me", headers=viewer_headers).status_code == 200
        assert client.get("/api/v1/auth/me", headers=viewer_headers).status_code == 200
        denied = client.get("/api/v1/auth/me", headers=viewer_headers)
        independent = client.get("/api/v1/auth/me", headers=analyst_headers)

    assert denied.status_code == 429
    assert viewer not in denied.text
    assert independent.status_code == 200


def test_invalid_tokens_return_401_without_consuming_a_user_bucket() -> None:
    with _client(_settings(login_capacity=10, standard_capacity=1)) as client:
        token = _login(client)
        invalid = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.jwt"})
        first_valid = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        denied = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert invalid.status_code == 401
    assert first_valid.status_code == 200
    assert denied.status_code == 429


def test_explicit_disabled_mode_does_not_limit_requests() -> None:
    with _client(_settings(enabled=False, login_capacity=1, standard_capacity=1)) as client:
        token = _login(client)
        for _ in range(5):
            response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            assert response.headers["X-RateLimit-Limit"] == "1"


class FailingStore:
    async def consume(self, *args: object, **kwargs: object) -> None:
        raise RateLimitStoreError("private store detail")


def test_store_failure_fails_closed_with_sanitized_503() -> None:
    settings = _settings()
    with _client(settings) as client:
        client.app.state.rate_limiter = TokenBucketRateLimiter(
            enabled=True,
            policies=policies_from_settings(settings),
            store=FailingStore(),
            clock=ManualClock(),
        )
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "unknown", "password": "Invalid-Test-Password"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency.unavailable"
    assert "private store detail" not in response.text
    assert "Traceback" not in response.text
