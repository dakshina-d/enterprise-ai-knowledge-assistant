"""Native FastAPI SSE adaptation for the public graph stream."""

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from typing import cast
from uuid import uuid4

from fastapi import Request
from fastapi.sse import ServerSentEvent

from enterprise_ai.api.errors import exception_status, log_unexpected, public_error
from enterprise_ai.api.schemas import ChatStreamEnvelope, PublicAPIError
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput, GraphOutput, GraphStreamItem
from enterprise_ai.models.events import AgentEvent, AgentEventType

TERMINAL_EVENTS = {
    AgentEventType.RESPONSE_COMPLETED,
    AgentEventType.RESPONSE_FAILED,
}
logger = logging.getLogger(__name__)


async def chat_event_stream(
    request: Request,
    runtime: GraphRuntime,
    graph_input: GraphInput,
    *,
    ping_seconds: float,
) -> AsyncIterator[ServerSentEvent]:
    """Emit safe events and close the graph iterator on disconnect or cancellation."""
    sequence = 0
    iterator = cast(AsyncGenerator[GraphStreamItem, None], runtime.astream(graph_input))
    pending: asyncio.Future[GraphStreamItem] | None = None
    terminal_event: AgentEvent | None = None

    def message(
        event_type: str,
        *,
        agent_event: AgentEvent | None = None,
        response: GraphOutput | None = None,
        error: PublicAPIError | None = None,
    ) -> ServerSentEvent:
        nonlocal sequence
        envelope = ChatStreamEnvelope(
            event_id=uuid4(),
            sequence=sequence,
            request_id=graph_input.request_id,
            trace_id=graph_input.trace_id,
            session_id=graph_input.session_id,
            event_type=event_type,
            agent_event=agent_event,
            response=response,
            error=error,
        )
        sequence += 1
        return ServerSentEvent(
            event=event_type,
            id=str(envelope.event_id),
            data=envelope.model_dump(mode="json", exclude_none=True),
        )

    yield message("stream.started")
    try:
        while True:
            pending = asyncio.ensure_future(anext(iterator))
            while not pending.done():
                done, _ = await asyncio.wait({pending}, timeout=ping_seconds)
                if done:
                    break
                if await request.is_disconnected():
                    pending.cancel()
                    with suppress(asyncio.CancelledError):
                        await pending
                    raise asyncio.CancelledError
                yield ServerSentEvent(comment="keepalive")
            try:
                item = pending.result()
            except StopAsyncIteration:
                break
            finally:
                pending = None
            if item.event is not None:
                if item.event.event_type in TERMINAL_EVENTS:
                    terminal_event = item.event
                    continue
                yield message(item.event.event_type.value, agent_event=item.event)
                continue
            if item.output is not None:
                event_type = (
                    terminal_event.event_type.value
                    if terminal_event is not None
                    else AgentEventType.RESPONSE_COMPLETED.value
                )
                yield message(
                    event_type,
                    agent_event=terminal_event,
                    response=item.output,
                )
                logger.info(
                    "chat_stream_completed",
                    extra={
                        "request_id": str(graph_input.request_id),
                        "trace_id": str(graph_input.trace_id),
                        "session_id": str(graph_input.session_id),
                        "role": graph_input.principal.identity.role.value,
                        "route": item.output.selected_route.value,
                        "completion_status": item.output.completion_status.value,
                        "outcome": "completed",
                    },
                )
                return
        yield message(
            "stream.error",
            error=public_error(
                request,
                RuntimeError("graph stream ended without a final output"),
            ),
        )
    except asyncio.CancelledError:
        logger.info(
            "chat_stream_cancelled",
            extra={
                "request_id": str(graph_input.request_id),
                "trace_id": str(graph_input.trace_id),
                "session_id": str(graph_input.session_id),
                "role": graph_input.principal.identity.role.value,
                "outcome": "cancelled",
                "cancelled": True,
                "disconnected": True,
            },
        )
        raise
    except Exception as error:
        if exception_status(error) == 500:
            log_unexpected(request)
        logger.warning(
            "chat_stream_failed",
            extra={
                "request_id": str(graph_input.request_id),
                "trace_id": str(graph_input.trace_id),
                "session_id": str(graph_input.session_id),
                "role": graph_input.principal.identity.role.value,
                "dependency_category": "graph",
                "outcome": "failed",
            },
        )
        yield message("stream.error", error=public_error(request, error))
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
        await iterator.aclose()
