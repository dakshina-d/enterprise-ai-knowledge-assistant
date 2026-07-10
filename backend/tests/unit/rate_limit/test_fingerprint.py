"""Tests for conservative anonymous-client fingerprint selection."""

import pytest
from enterprise_ai.core.config import Settings
from enterprise_ai.rate_limit.dependencies import (
    RateLimitUnavailableError,
    anonymous_fingerprint,
)
from starlette.requests import Request


def _request(host: str, forwarded: str | None = None) -> Request:
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": headers, "client": (host, 1234)}
    )


def test_proxy_header_is_ignored_by_default() -> None:
    settings = Settings(trust_proxy_headers=False)
    direct = anonymous_fingerprint(_request("203.0.113.10"), settings)
    spoofed = anonymous_fingerprint(_request("203.0.113.10", "198.51.100.1"), settings)
    assert direct == spoofed
    assert "203.0.113.10" not in direct


def test_single_forwarded_hop_requires_explicit_trusted_proxy() -> None:
    settings = Settings(trust_proxy_headers=True, trusted_proxy_hosts="10.0.0.1")
    trusted = anonymous_fingerprint(_request("10.0.0.1", "198.51.100.1"), settings)
    untrusted = anonymous_fingerprint(_request("10.0.0.2", "198.51.100.1"), settings)
    assert trusted != untrusted


@pytest.mark.parametrize("forwarded", ["not-an-ip", "198.51.100.1, 10.0.0.1"])
def test_malformed_trusted_forwarded_header_fails_closed(forwarded: str) -> None:
    settings = Settings(trust_proxy_headers=True, trusted_proxy_hosts="10.0.0.1")
    with pytest.raises(RateLimitUnavailableError):
        anonymous_fingerprint(_request("10.0.0.1", forwarded), settings)
