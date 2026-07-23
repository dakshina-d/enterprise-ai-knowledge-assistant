"""Safe HTTP translation for authentication and authorization errors."""

import logging
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from enterprise_ai.models.errors import ApplicationErrorResponse
from enterprise_ai.security.exceptions import SecurityError

logger = logging.getLogger(__name__)


async def security_error_handler(request: Request, error: SecurityError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4())
    trace_id = getattr(request.state, "trace_id", None)
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
