"""Separated public error contracts and internal diagnostic context."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from enterprise_ai.models.common import ContractModel, RequestId, TraceId


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    DEPENDENCY = "dependency"
    TIMEOUT = "timeout"
    SECURITY_POLICY = "security_policy"
    PARTIAL_RESULT = "partial_result"
    INTERNAL = "internal"


class ErrorCode(StrEnum):
    INVALID_REQUEST = "validation.invalid_request"
    AUTHENTICATION_REQUIRED = "authentication.required"
    AUTHENTICATION_FAILED = "authentication.failed"
    AUTHORIZATION_DENIED = "authorization.denied"
    RATE_LIMIT_EXCEEDED = "rate_limit.exceeded"
    DEPENDENCY_UNAVAILABLE = "dependency.unavailable"
    DEPENDENCY_TIMEOUT = "timeout.dependency"
    SECURITY_POLICY_VIOLATION = "security_policy.violation"
    PARTIAL_RESULT = "partial_result.available"
    INTERNAL_ERROR = "internal.unexpected"


class ErrorSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ValidationDetail(ContractModel):
    field: Annotated[str, Field(min_length=1, max_length=200)]
    code: Annotated[str, Field(min_length=1, max_length=100)]
    message: Annotated[str, Field(min_length=1, max_length=500)]


class ApplicationErrorResponse(ContractModel):
    category: ErrorCategory
    code: ErrorCode
    message: Annotated[str, Field(min_length=1, max_length=500)]
    request_id: RequestId
    trace_id: TraceId | None = None
    retryable: bool = False
    retry_after_seconds: Annotated[int | None, Field(ge=1, le=86_400)] = None
    validation_details: tuple[ValidationDetail, ...] = ()


class InternalErrorContext(ContractModel):
    """Internal-only diagnostic metadata; never nest in public responses."""

    category: ErrorCategory
    code: ErrorCode
    severity: ErrorSeverity
    request_id: RequestId
    trace_id: TraceId | None = None
    operation: Annotated[str, Field(min_length=1, max_length=200)]
    dependency: Annotated[str | None, Field(max_length=100)] = None
    attempt: Annotated[int, Field(ge=0, le=10)] = 0
    diagnostic_message: Annotated[str, Field(min_length=1, max_length=2_000)]


class DependencyFailure(ContractModel):
    dependency: Annotated[str, Field(min_length=1, max_length=100)]
    code: ErrorCode
    retryable: bool
    attempts: Annotated[int, Field(ge=0, le=10)]
    safe_message: Annotated[str, Field(min_length=1, max_length=500)]


class PartialResultWarning(ContractModel):
    code: ErrorCode = ErrorCode.PARTIAL_RESULT
    safe_message: Annotated[str, Field(min_length=1, max_length=500)]
    unavailable_capability: Annotated[str | None, Field(max_length=100)] = None
