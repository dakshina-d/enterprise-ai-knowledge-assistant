"""Safe HTTP translation for rate-limit denials and enforcement failures."""

import logging
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from enterprise_ai.models.errors import ApplicationErrorResponse, ErrorCategory, ErrorCode
from enterprise_ai.rate_limit.dependencies import (
    RateLimitExceededError,
    RateLimitUnavailableError,
)
from enterprise_ai.rate_limit.token_bucket import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


async def rate_limit_exceeded_handler(
    request: Request, error: RateLimitExceededError
) -> JSONResponse:
    request_id, trace_id = _correlation(request)
    decision = error.decision
    logger.warning(
        "rate_limit_denied",
        extra={
            "request_id": str(request_id),
            "trace_id": str(trace_id) if trace_id else None,
            "policy": decision.policy_name.value,
            "outcome": "denied",
            "requested_cost": decision.requested_cost,
            "remaining_tokens": decision.remaining_tokens,
            "retry_after": decision.retry_after_seconds,
            "reason_code": decision.reason_code.value,
            "subject_category": decision.subject_category.value,
        },
    )
    response = ApplicationErrorResponse(
        category=ErrorCategory.RATE_LIMIT,
        code=ErrorCode.RATE_LIMIT_EXCEEDED,
        message="Too many requests. Please try again later.",
        request_id=request_id,
        trace_id=trace_id,
        retryable=True,
        retry_after_seconds=decision.retry_after_seconds,
    )
    headers = TokenBucketRateLimiter.headers_for(decision).as_http_headers()
    return JSONResponse(
        status_code=429,
        content={"error": response.model_dump(mode="json")},
        headers=headers,
    )


async def rate_limit_unavailable_handler(
    request: Request, error: RateLimitUnavailableError
) -> JSONResponse:
    request_id, trace_id = _correlation(request)
    logger.error(
        "rate_limit_enforcement_failed",
        extra={"request_id": str(request_id), "outcome": "failed"},
    )
    response = ApplicationErrorResponse(
        category=ErrorCategory.DEPENDENCY,
        code=ErrorCode.DEPENDENCY_UNAVAILABLE,
        message="Request protection is temporarily unavailable.",
        request_id=request_id,
        trace_id=trace_id,
        retryable=True,
    )
    return JSONResponse(status_code=503, content={"error": response.model_dump(mode="json")})


def _correlation(request: Request) -> tuple[UUID, UUID | None]:
    return _identifier(request.headers.get("X-Request-ID")) or uuid4(), _identifier(
        request.headers.get("X-Trace-ID")
    )


def _identifier(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
