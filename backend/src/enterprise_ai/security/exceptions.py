"""Typed security exceptions translated safely at the HTTP boundary."""

from http import HTTPStatus

from enterprise_ai.models.errors import ErrorCategory, ErrorCode


class SecurityError(Exception):
    def __init__(
        self,
        *,
        status_code: HTTPStatus,
        category: ErrorCategory,
        code: ErrorCode,
        public_message: str,
        reason_code: str,
    ) -> None:
        super().__init__(public_message)
        self.status_code = status_code
        self.category = category
        self.code = code
        self.public_message = public_message
        self.reason_code = reason_code


class AuthenticationError(SecurityError):
    def __init__(self, *, reason_code: str = "authentication.invalid") -> None:
        super().__init__(
            status_code=HTTPStatus.UNAUTHORIZED,
            category=ErrorCategory.AUTHENTICATION,
            code=ErrorCode.AUTHENTICATION_FAILED,
            public_message="Authentication credentials are invalid or expired.",
            reason_code=reason_code,
        )


class AuthenticationRequiredError(SecurityError):
    def __init__(self) -> None:
        super().__init__(
            status_code=HTTPStatus.UNAUTHORIZED,
            category=ErrorCategory.AUTHENTICATION,
            code=ErrorCode.AUTHENTICATION_REQUIRED,
            public_message="Bearer authentication is required.",
            reason_code="authentication.missing",
        )


class AuthorizationError(SecurityError):
    def __init__(self, *, reason_code: str = "authorization.denied") -> None:
        super().__init__(
            status_code=HTTPStatus.FORBIDDEN,
            category=ErrorCategory.AUTHORIZATION,
            code=ErrorCode.AUTHORIZATION_DENIED,
            public_message="You are not authorized to perform this operation.",
            reason_code=reason_code,
        )
