"""Bounded synchronous HTTP client for Streamlit login and POST SSE chat."""

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import httpx
from enterprise_ai.api.schemas import ChatStreamEnvelope
from enterprise_ai.models.identity import LoginResponse

from frontend.enterprise_ai_frontend.config import FrontendSettings
from frontend.enterprise_ai_frontend.errors import (
    AuthenticationExpiredError,
    FrontendError,
    SSEProtocolError,
)
from frontend.enterprise_ai_frontend.sse import (
    SSEParser,
    StreamContractValidator,
    decode_envelope,
)

MAXIMUM_ERROR_BODY_BYTES = 32_000


class APIClient:
    def __init__(
        self,
        settings: FrontendSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def login(self, username: str, password: str) -> LoginResponse:
        try:
            with self._client() as client:
                with client.stream(
                    "POST",
                    "/api/v1/auth/login",
                    json={"username": username, "password": password},
                ) as response:
                    body = _bounded_body(response)
                    if response.status_code == 401:
                        raise FrontendError(
                            "The username or password was not accepted.",
                            code="authentication.failed",
                        )
                    if response.status_code != 200:
                        raise self._http_error(response, body)
                    try:
                        if body is None:
                            raise ValueError("authentication response exceeded the safe size limit")
                        return LoginResponse.model_validate(json.loads(body))
                    except ValueError as error:
                        raise SSEProtocolError(
                            "The authentication response was invalid."
                        ) from error
        except FrontendError:
            raise
        except (httpx.TimeoutException, httpx.RequestError) as error:
            raise FrontendError(
                "The authentication service is unavailable.",
                code="frontend.backend_unavailable",
                retryable=True,
            ) from error

    def stream_chat(
        self,
        *,
        access_token: str,
        message: str,
        session_id: UUID | None,
    ) -> Iterator[ChatStreamEnvelope]:
        body: dict[str, object] = {"message": message}
        if session_id is not None:
            body["session_id"] = str(session_id)
        parser = SSEParser()
        validator = StreamContractValidator()
        try:
            with self._client(streaming=True) as client:
                with client.stream(
                    "POST",
                    "/api/v1/chat/stream",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "text/event-stream",
                    },
                    json=body,
                ) as response:
                    if response.status_code != 200:
                        error_body = _bounded_body(response)
                        raise self._http_error(response, error_body)
                    if not response.headers.get("Content-Type", "").startswith("text/event-stream"):
                        raise SSEProtocolError()
                    for chunk in response.iter_bytes(chunk_size=1_024):
                        for raw_event in parser.feed(chunk):
                            envelope = decode_envelope(raw_event)
                            validator.accept(envelope)
                            yield envelope
                    parser.finish()
                    validator.finish()
        except FrontendError:
            raise
        except (httpx.TimeoutException, httpx.RequestError) as error:
            raise FrontendError(
                "The activity stream was interrupted.",
                code="frontend.stream_interrupted",
                retryable=True,
            ) from error

    def _client(self, *, streaming: bool = False) -> httpx.Client:
        timeout = httpx.Timeout(
            connect=self._settings.request_timeout_seconds,
            read=(
                self._settings.stream_timeout_seconds
                if streaming
                else self._settings.request_timeout_seconds
            ),
            write=self._settings.request_timeout_seconds,
            pool=self._settings.request_timeout_seconds,
        )
        return httpx.Client(
            base_url=str(self._settings.api_base_url),
            timeout=timeout,
            transport=self._transport,
            follow_redirects=False,
        )

    @staticmethod
    def _http_error(response: httpx.Response, body: bytes | None) -> FrontendError:
        if response.status_code == 401:
            return AuthenticationExpiredError()
        retry_after = _retry_after(response.headers.get("Retry-After"))
        code = f"http.{response.status_code}"
        message = _default_message(response.status_code)
        retryable = response.status_code in {429, 500, 503, 504}
        if body is not None:
            parsed = _safe_error_fields(body)
            if parsed is not None:
                code, message, retryable = parsed
        return FrontendError(
            public_message=message,
            code=code,
            retryable=retryable,
            retry_after_seconds=retry_after,
        )


def _bounded_body(response: httpx.Response) -> bytes | None:
    content = bytearray()
    for chunk in response.iter_bytes(chunk_size=4_096):
        content.extend(chunk)
        if len(content) > MAXIMUM_ERROR_BODY_BYTES:
            return None
    return bytes(content)


def _safe_error_fields(body_bytes: bytes) -> tuple[str, str, bool] | None:
    try:
        body: Any = json.loads(body_bytes)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return None
    error = body["error"]
    code = error.get("code")
    message = error.get("message")
    retryable = error.get("retryable", False)
    if (
        not isinstance(code, str)
        or len(code) > 100
        or not isinstance(message, str)
        or len(message) > 500
        or not isinstance(retryable, bool)
    ):
        return None
    return code, message, retryable


def _retry_after(value: str | None) -> int | None:
    try:
        parsed = int(value) if value is not None else None
    except ValueError:
        return None
    return parsed if parsed is not None and 1 <= parsed <= 86_400 else None


def _default_message(status_code: int) -> str:
    return {
        400: "The request was invalid.",
        401: "Your session has expired. Please sign in again.",
        409: "This conversation cannot be continued. Start a new conversation.",
        422: "The message could not be accepted.",
        429: "Too many requests. Please wait before trying again.",
        500: "The assistant could not complete the request safely.",
        503: "A required service is temporarily unavailable.",
        504: "The assistant timed out before completing the request.",
    }.get(status_code, "The request could not be completed.")
