from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput, GraphOutput
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import AgentEventStatus, AgentEventType
from enterprise_ai.models.graph import Intent, PublicAgentStatus, Route
from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal


class InvalidThenTerminalGraph:
    def __init__(self, request: GraphInput, invalid: dict[str, object]) -> None:
        self.request = request
        self.invalid = invalid

    async def astream(self, *args: object, **kwargs: object) -> AsyncIterator[dict[str, object]]:
        yield {"type": "custom", "data": self.invalid}
        yield {
            "type": "custom",
            "data": {
                "event_type": AgentEventType.RESPONSE_FAILED,
                "sequence_number": 0,
                "request_id": self.request.request_id,
                "trace_id": self.request.trace_id,
                "session_id": self.request.session_id,
                "status": AgentEventStatus.FAILED,
                "public_message": "Request failed safely.",
            },
        }
        output = GraphOutput(
            graph_version="1.2",
            request_id=self.request.request_id,
            trace_id=self.request.trace_id,
            session_id=self.request.session_id,
            completion_status=ProcessingStatus.FAILED,
            selected_route=Route.FAILURE,
            intent=Intent.UNSUPPORTED,
            response_text="Request failed safely.",
            agent_status=PublicAgentStatus(
                request_id=self.request.request_id,
                status=ProcessingStatus.FAILED,
                node="finalize_execution",
                public_message="Failed safely.",
                route=Route.FAILURE,
                recursion_depth=0,
            ),
        )
        yield {"type": "values", "data": {"final_output": output}}


def _request() -> GraphInput:
    return GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(UserRole.VIEWER),
        user_message="hello",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    (
        {"unknown": object()},
        {"event_type": "node.completed", "sequence_number": -1},
        {"event_type": "node.completed", "sequence_number": 0, "public_message": "x" * 501},
    ),
)
async def test_invalid_public_event_is_dropped_before_safe_terminal(
    invalid: dict[str, object],
) -> None:
    request = _request()
    runtime = GraphRuntime(InvalidThenTerminalGraph(request, invalid), RetrievalSettings())
    items = [item async for item in runtime.astream(request)]
    assert len(items) == 2
    assert items[0].event and items[0].event.event_type is AgentEventType.RESPONSE_FAILED
    assert items[1].output and items[1].output.completion_status is ProcessingStatus.FAILED
