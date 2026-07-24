"""Bounded standard-library health smoke check for the local Compose stack."""

from __future__ import annotations

import argparse
import http.client
import json
import time
import urllib.error
import urllib.request


def wait_for_health(name: str, url: str, timeout_seconds: float) -> None:
    """Poll a JSON or text health endpoint until it is healthy or the deadline expires."""
    deadline = time.monotonic() + timeout_seconds
    last_category = "unavailable"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                body = response.read(4096)
                if response.status == 200 and _healthy_body(body):
                    print(f"{name}: healthy")
                    return
                last_category = f"http_{response.status}"
        except (TimeoutError, urllib.error.URLError, http.client.HTTPException):
            last_category = "unavailable"
        time.sleep(0.5)
    raise SystemExit(f"{name}: health check failed ({last_category})")


def _healthy_body(body: bytes) -> bool:
    text = body.decode("utf-8", errors="replace").strip()
    if text.casefold() == "ok":
        return True
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("status") == "healthy"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/health/ready")
    parser.add_argument("--ui-url", default="http://127.0.0.1:8501/_stcore/health")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    arguments = parser.parse_args()
    if arguments.timeout_seconds <= 0 or arguments.timeout_seconds > 300:
        raise SystemExit("timeout must be greater than zero and at most 300 seconds")
    wait_for_health("api", arguments.api_url, arguments.timeout_seconds)
    wait_for_health("ui", arguments.ui_url, arguments.timeout_seconds)


if __name__ == "__main__":
    main()
