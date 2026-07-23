"""Safe frontend failures that never include raw transport bodies or credentials."""

from dataclasses import dataclass


@dataclass
class FrontendError(Exception):
    public_message: str
    code: str = "frontend.unavailable"
    retryable: bool = False
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.public_message


class AuthenticationExpiredError(FrontendError):
    def __init__(self) -> None:
        super().__init__(
            public_message="Your session has expired. Please sign in again.",
            code="authentication.expired",
        )


class SSEProtocolError(FrontendError):
    def __init__(self, message: str = "The activity stream was invalid or incomplete.") -> None:
        super().__init__(public_message=message, code="stream.protocol_error", retryable=True)
