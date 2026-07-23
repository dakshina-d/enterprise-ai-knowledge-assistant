"""Cancellation behavior for the graph-to-SSE adapter."""

import asyncio
from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import pytest
from enterprise_ai.api.sse import chat_event_stream
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput, GraphStreamItem
from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.evaluation import assessment_principal
from fastapi import Request


class BlockingRuntime:
    def __init__(self) -> None:
        self.closed = asyncio.Event()

    async def astream(self, _graph_input: GraphInput) -> AsyncIterator[GraphStreamItem]:
        try:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
            yield
        finally:
            self.closed.set()


@pytest.mark.asyncio
async def test_disconnect_cancels_and_closes_the_graph_iterator() -> None:
    runtime = BlockingRuntime()

    async def receive() -> dict[str, str]:
        return {"type": "http.disconnect"}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/chat/stream",
            "headers": [],
        },
        receive,
    )
    graph_input = GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(UserRole.ANALYST),
        user_message="hello",
    )
    stream = chat_event_stream(
        request,
        cast(GraphRuntime, runtime),
        graph_input,
        ping_seconds=0.01,
    )

    assert (await anext(stream)).event == "stream.started"
    with pytest.raises(asyncio.CancelledError):
        await anext(stream)
    assert runtime.closed.is_set()
