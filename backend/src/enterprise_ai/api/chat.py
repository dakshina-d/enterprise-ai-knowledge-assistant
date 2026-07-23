"""Authenticated asynchronous JSON and SSE chat endpoints."""

import logging
from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent

from enterprise_ai.api.errors import ChatAPIError, exception_status, log_unexpected, public_error
from enterprise_ai.api.schemas import ChatRequest, PublicAPIErrorEnvelope
from enterprise_ai.api.sse import chat_event_stream
from enterprise_ai.core.config import Settings
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput, GraphOutput
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.rate_limit.dependencies import RateLimitedPrincipal

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def get_graph_runtime(request: Request) -> GraphRuntime:
    return cast(GraphRuntime, request.app.state.graph_runtime)


def get_api_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


GraphRuntimeDependency = Annotated[GraphRuntime, Depends(get_graph_runtime)]
SettingsDependency = Annotated[Settings, Depends(get_api_settings)]


def _graph_input(
    request: Request,
    body: ChatRequest,
    principal: AuthenticatedPrincipal,
) -> GraphInput:
    return GraphInput(
        request_id=request.state.request_id,
        trace_id=request.state.trace_id,
        session_id=body.session_id or uuid4(),
        principal=principal,
        user_message=body.message,
        requested_top_k=body.top_k,
    )


@router.post(
    "",
    response_model=GraphOutput,
    responses={
        401: {"model": PublicAPIErrorEnvelope},
        409: {"model": PublicAPIErrorEnvelope},
        422: {"model": PublicAPIErrorEnvelope},
        429: {"model": PublicAPIErrorEnvelope},
        500: {"model": PublicAPIErrorEnvelope},
        504: {"model": PublicAPIErrorEnvelope},
    },
)
async def chat(
    request: Request,
    body: ChatRequest,
    principal: RateLimitedPrincipal,
    runtime: GraphRuntimeDependency,
) -> GraphOutput:
    graph_input = _graph_input(request, body, principal)
    try:
        output = await runtime.ainvoke(graph_input)
    except Exception as error:
        status_code = exception_status(error)
        safe_error = public_error(request, error)
        if status_code == 500:
            log_unexpected(request)
        raise ChatAPIError(
            status_code=status_code,
            code=safe_error.code,
            public_message=safe_error.message,
            retryable=safe_error.retryable,
        ) from error
    logger.info(
        "chat_request_completed",
        extra={
            "request_id": str(output.request_id),
            "trace_id": str(output.trace_id),
            "session_id": str(output.session_id),
            "endpoint": request.url.path,
            "role": principal.identity.role.value,
            "completion_status": output.completion_status.value,
            "selected_route": output.selected_route.value,
            "outcome": "completed",
        },
    )
    return output


@router.post(
    "/stream",
    response_class=EventSourceResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": (
                "Native SSE stream containing application-owned JSON envelopes. "
                "Consume this POST response with an HTTP streaming client."
            ),
        },
        401: {"model": PublicAPIErrorEnvelope},
        422: {"model": PublicAPIErrorEnvelope},
        429: {"model": PublicAPIErrorEnvelope},
    },
)
async def chat_stream(
    request: Request,
    response: Response,
    body: ChatRequest,
    _principal: RateLimitedPrincipal,
    runtime: GraphRuntimeDependency,
    settings: SettingsDependency,
) -> AsyncIterator[ServerSentEvent]:
    graph_input = _graph_input(request, body, _principal)
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    async for event in chat_event_stream(
        request,
        runtime,
        graph_input,
        ping_seconds=settings.api_sse_ping_seconds,
    ):
        yield event
