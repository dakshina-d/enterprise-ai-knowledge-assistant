"""Bounded async runtime around the compiled baseline graph."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from langsmith import tracing_context
from pydantic import ValidationError

from enterprise_ai.graph.schemas import GraphInput, GraphOutput, GraphStreamItem
from enterprise_ai.llm.response_service import GroundedResponseService
from enterprise_ai.memory.service import ConversationMemoryService
from enterprise_ai.models.events import AgentEvent, AgentEventType
from enterprise_ai.models.graph import GraphError
from enterprise_ai.models.identity import ToolPermission, UserRole
from enterprise_ai.observability.tracing import SafeTracer, create_tracer
from enterprise_ai.retrieval.config import RetrievalSettings

logger = logging.getLogger(__name__)


class SessionOwnershipError(PermissionError):
    """Raised when a checkpoint thread is reused by another user."""


class GraphRuntime:
    def __init__(
        self,
        graph: Any,  # noqa: ANN401
        settings: RetrievalSettings,
        memory: ConversationMemoryService | None = None,
        responses: GroundedResponseService | None = None,
        tracer: SafeTracer | None = None,
    ) -> None:
        self._graph = graph
        self._settings = settings
        self._session_owners: dict[UUID, tuple[UUID, UserRole, frozenset[ToolPermission]]] = {}
        self._ownership_lock = asyncio.Lock()
        self._memory = memory
        self._responses = responses
        self._tracer = tracer or create_tracer(settings)

    def _trace_metadata(self, graph_input: GraphInput) -> dict[str, object]:
        return {
            "application_version": "0.1.0",
            "graph_version": "1.2",
            "environment": self._settings.app_env,
            "user_role": graph_input.principal.identity.role,
            "permission_count": len(graph_input.principal.permissions),
            "request_id": graph_input.request_id,
            "trace_id": graph_input.trace_id,
            "session_id": graph_input.session_id,
            "query_characters": len(graph_input.user_message),
        }

    @staticmethod
    def _outcome_metadata(output: GraphOutput) -> dict[str, object]:
        return {
            "completion_status": output.completion_status,
            "route": output.selected_route,
            "evidence_count": len(output.evidence),
            "citation_valid": all(
                report.result.value != "failed" for report in output.validation_reports
            ),
            "deterministic_fallback_used": output.deterministic_fallback_used,
            "deterministic_analysis_rendering_used": (output.deterministic_analysis_rendering_used),
            "fallback_reason": output.fallback_reason,
            "insufficient_evidence": output.insufficient_evidence,
        }

    async def _claim_session(self, graph_input: GraphInput) -> None:
        principal = graph_input.principal
        claim = (
            principal.identity.user_id,
            principal.identity.role,
            principal.permissions,
        )
        async with self._ownership_lock:
            owner = self._session_owners.setdefault(graph_input.session_id, claim)
            if owner != claim:
                raise SessionOwnershipError("session belongs to another authenticated principal")

    def _config(self, graph_input: GraphInput) -> dict[str, Any]:
        return {
            "configurable": {
                "thread_id": str(graph_input.session_id),
            },
            "recursion_limit": self._settings.graph_max_steps + 4,
            "run_name": "enterprise-ai-baseline",
            "tags": ["baseline-graph", "offline-safe"],
            "metadata": {
                "request_id": str(graph_input.request_id),
                "session_id": str(graph_input.session_id),
                "user_role": graph_input.principal.identity.role.value,
                "graph_version": "1.2",
            },
        }

    @staticmethod
    def _base_state(graph_input: GraphInput) -> dict[str, object]:
        return {
            "request_id": graph_input.request_id,
            "trace_id": graph_input.trace_id,
            "session_id": graph_input.session_id,
            "principal": graph_input.principal,
            "user_message": graph_input.user_message,
            "retrieval_filters": graph_input.retrieval_filters,
            "requested_top_k": graph_input.requested_top_k,
            "invocation_timestamp": graph_input.invocation_timestamp,
            "original_query": graph_input.user_message,
            "retrieved_evidence": (),
            "validation_reports": (),
            "warnings": (),
            "errors": (),
            "visited_nodes": (),
            "activity_events": (),
        }

    def _initial_state(self, graph_input: GraphInput) -> dict[str, object]:
        state = self._base_state(graph_input)
        if len(graph_input.user_message) > self._settings.graph_max_message_characters:
            state["failure"] = True
            state["errors"] = (
                GraphError(
                    code="graph.message_character_budget_exceeded",
                    safe_message="Message character budget was exceeded.",
                    node="validate_request",
                ),
            )
        return state

    async def _execute(self, graph_input: GraphInput) -> dict[str, Any]:
        await self._claim_session(graph_input)
        async with self._tracer.span(
            "enterprise_ai_assistant", "chain", self._trace_metadata(graph_input)
        ) as span:
            # A small outer grace lets the node-local deadline route through handle_failure.
            async with asyncio.timeout(self._settings.graph_timeout_seconds + 0.25):
                with tracing_context(enabled=False):
                    result = await self._graph.ainvoke(
                        self._initial_state(graph_input), config=self._config(graph_input)
                    )
            try:
                output = GraphOutput.model_validate(result.get("final_output"))
            except ValidationError:
                pass
            else:
                if span is not None:
                    span.update_metadata(self._outcome_metadata(output))
        return dict(result)

    async def ainvoke(self, graph_input: GraphInput) -> GraphOutput:
        try:
            state = await self._execute(graph_input)
            output = GraphOutput.model_validate(state["final_output"])
        except asyncio.CancelledError:
            self._log_outcome(graph_input, outcome="cancelled", cancelled=True)
            raise
        except Exception:
            self._log_outcome(graph_input, outcome="failed", dependency_category="graph")
            raise
        self._log_outcome(
            graph_input,
            outcome="completed",
            route=output.selected_route.value,
            completion_status=output.completion_status.value,
            fallback_reason=output.fallback_reason.value if output.fallback_reason else None,
        )
        return output

    async def astream(self, graph_input: GraphInput) -> AsyncIterator[GraphStreamItem]:
        """Parse LangGraph v2 custom/value stream parts into the public contract."""
        async with self._tracer.span(
            "enterprise_ai_assistant", "chain", self._trace_metadata(graph_input)
        ) as span:
            output_seen = False
            async for item in self._astream_untraced(graph_input):
                if item.output is not None:
                    output_seen = True
                    if span is not None:
                        span.update_metadata(self._outcome_metadata(item.output))
                    self._log_outcome(
                        graph_input,
                        outcome="completed",
                        route=item.output.selected_route.value,
                        completion_status=item.output.completion_status.value,
                        fallback_reason=(
                            item.output.fallback_reason.value
                            if item.output.fallback_reason
                            else None
                        ),
                    )
                yield item
            if span is not None and not output_seen:
                span.update_metadata({"completion_status": "partial_success"})

    async def _astream_untraced(self, graph_input: GraphInput) -> AsyncIterator[GraphStreamItem]:
        await self._claim_session(graph_input)
        output_emitted = False
        terminal_seen = False
        expected_sequence = 0
        async with asyncio.timeout(self._settings.graph_timeout_seconds + 0.25):
            async for part in self._graph_parts(graph_input):
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                data = part.get("data")
                if part_type == "custom":
                    try:
                        public_event = AgentEvent.model_validate(data)
                    except ValidationError:
                        continue
                    if terminal_seen:
                        continue
                    if (
                        public_event.sequence_number != expected_sequence
                        or public_event.request_id != graph_input.request_id
                        or public_event.trace_id != graph_input.trace_id
                        or public_event.session_id != graph_input.session_id
                    ):
                        continue
                    expected_sequence += 1
                    terminal_seen = public_event.event_type in {
                        AgentEventType.RESPONSE_COMPLETED,
                        AgentEventType.RESPONSE_FAILED,
                    }
                    yield GraphStreamItem(event=public_event)
                elif (
                    part_type == "values"
                    and isinstance(data, dict)
                    and "final_output" in data
                    and terminal_seen
                    and not output_emitted
                ):
                    output_emitted = True
                    yield GraphStreamItem(output=GraphOutput.model_validate(data["final_output"]))

    async def _graph_parts(self, graph_input: GraphInput) -> AsyncIterator[object]:
        """Suppress automatic state capture while application-owned safe spans run."""
        with tracing_context(enabled=False):
            async for part in self._graph.astream(
                self._initial_state(graph_input),
                config=self._config(graph_input),
                stream_mode=["custom", "values"],
                version="v2",
            ):
                yield part

    async def inspect_state(self, graph_input: GraphInput) -> object:
        """Inspect the request-scoped checkpoint without exposing it in public output."""
        await self._claim_session(graph_input)
        return await self._graph.aget_state(self._config(graph_input))

    async def inspect_memory(self, graph_input: GraphInput) -> object:
        await self._claim_session(graph_input)
        if self._memory is None:
            return None
        return await self._memory.inspect(graph_input.session_id, graph_input.principal)

    async def aclose(self) -> None:
        if self._responses is not None:
            await self._responses.close()
        await self._tracer.flush()

    @staticmethod
    def _log_outcome(
        graph_input: GraphInput,
        *,
        outcome: str,
        route: str | None = None,
        completion_status: str | None = None,
        dependency_category: str | None = None,
        cancelled: bool = False,
        fallback_reason: str | None = None,
    ) -> None:
        logger.info(
            "graph_request_outcome",
            extra={
                "request_id": str(graph_input.request_id),
                "trace_id": str(graph_input.trace_id),
                "session_id": str(graph_input.session_id),
                "role": graph_input.principal.identity.role.value,
                "route": route,
                "completion_status": completion_status,
                "dependency_category": dependency_category,
                "outcome": outcome,
                "cancelled": cancelled,
                "fallback_reason": fallback_reason,
            },
        )
