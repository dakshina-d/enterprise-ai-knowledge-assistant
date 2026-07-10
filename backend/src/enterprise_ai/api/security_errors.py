"""Safe HTTP translation for authentication and authorization errors."""

import logging
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from enterprise_ai.models.errors import ApplicationErrorResponse
from enterprise_ai.security.exceptions import SecurityError

logger = logging.getLogger(__name__)


async def security_error_handler(request: Request, error: SecurityError) -> JSONResponse:
    request_id = _safe_identifier(request.headers.get("X-Request-ID"))
    trace_id = _optional_identifier(request.headers.get("X-Trace-ID"))
    logger.warning(
        "security_request_denied",
        extra={
            "request_id": str(request_id),
            "trace_id": str(trace_id) if trace_id else None,
            "outcome": "denied",
            "reason_code": error.reason_code,
        },
    )
    response = ApplicationErrorResponse(
        category=error.category,
        code=error.code,
        message=error.public_message,
        request_id=request_id,
        trace_id=trace_id,
    )
    headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
    return JSONResponse(
        status_code=int(error.status_code),
        content={"error": response.model_dump(mode="json")},
        headers=headers,
    )


def _safe_identifier(value: str | None) -> UUID:
    return _optional_identifier(value) or uuid4()


def _optional_identifier(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
