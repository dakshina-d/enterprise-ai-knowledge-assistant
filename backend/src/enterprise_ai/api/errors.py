"""Centralized safe HTTP error translation for chat delivery."""

import asyncio
import logging
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from enterprise_ai.api.schemas import PublicAPIError, PublicAPIErrorEnvelope
from enterprise_ai.graph.runtime import SessionOwnershipError
from enterprise_ai.memory.exceptions import MemoryOwnershipError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatAPIError(Exception):
    status_code: int
    code: str
    public_message: str
    retryable: bool = False


def request_identifier(request: Request) -> UUID:
    return cast(UUID, request.state.request_id)


def public_error(request: Request, error: Exception) -> PublicAPIError:
    request_id = request_identifier(request)
    if isinstance(error, (SessionOwnershipError, MemoryOwnershipError)):
        return PublicAPIError(
            code="session.ownership_conflict",
            message="The session cannot be used for this request.",
            request_id=request_id,
        )
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return PublicAPIError(
            code="timeout.graph",
            message="The assistant did not complete within the allowed time.",
            request_id=request_id,
            retryable=True,
        )
    if isinstance(error, ChatAPIError):
        return PublicAPIError(
            code=error.code,
            message=error.public_message,
            request_id=request_id,
            retryable=error.retryable,
        )
    return PublicAPIError(
        code="internal.unexpected",
        message="The request could not be completed safely.",
        request_id=request_id,
        retryable=True,
    )


async def chat_error_handler(request: Request, error: ChatAPIError) -> JSONResponse:
    return _response(error.status_code, public_error(request, error))


async def validation_error_handler(
    request: Request, _error: RequestValidationError
) -> JSONResponse:
    error = PublicAPIError(
        code="validation.invalid_request",
        message="The request body is invalid.",
        request_id=request_identifier(request),
    )
    return _response(422, error)


async def http_error_handler(request: Request, error: HTTPException) -> JSONResponse:
    if error.status_code == 404:
        public = PublicAPIError(
            code="resource.not_found",
            message="The requested API resource was not found.",
            request_id=request_identifier(request),
        )
        return _response(404, public)
    public = PublicAPIError(
        code="http.request_rejected",
        message="The HTTP request was rejected.",
        request_id=request_identifier(request),
    )
    return _response(error.status_code, public)


def exception_status(error: Exception) -> int:
    if isinstance(error, (SessionOwnershipError, MemoryOwnershipError)):
        return 409
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return 504
    if isinstance(error, ChatAPIError):
        return error.status_code
    return 500


def log_unexpected(request: Request) -> None:
    logger.error(
        "chat_request_failed",
        extra={
            "request_id": str(request_identifier(request)),
            "endpoint": request.url.path,
            "outcome": "failed",
        },
    )


def _response(status_code: int, error: PublicAPIError) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=PublicAPIErrorEnvelope(error=error).model_dump(mode="json"),
    )
