"""Deterministic asynchronous baseline graph nodes."""

import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from enterprise_ai.graph.dependencies import KnowledgeRetriever
from enterprise_ai.graph.events import event
from enterprise_ai.graph.routing import classify, supervise
from enterprise_ai.graph.schemas import GraphEvidenceAttribution, GraphOutput
from enterprise_ai.graph.state import GraphState
from enterprise_ai.memory.context import resolve_followup
from enterprise_ai.memory.exceptions import MemoryError
from enterprise_ai.memory.models import MemoryContext
from enterprise_ai.memory.service import ConversationMemoryService
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import AgentEventStatus, AgentEventType, PublicAgentEventPayload
from enterprise_ai.models.graph import (
    GraphError,
    Intent,
    PublicAgentStatus,
    Route,
    ValidationFinding,
    ValidationReport,
    ValidationResult,
)
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.exceptions import RetrievalError
from enterprise_ai.security.authorization import AuthorizationService


def _node_events(state: GraphState, node: str, message: str) -> tuple[object, ...]:
    started = event(
        state, AgentEventType.NODE_STARTED, AgentEventStatus.STARTED, f"{node} started.", node=node
    )
    next_state = cast(GraphState, dict(state))
    next_state["activity_events"] = (*state.get("activity_events", ()), started)
    completed = event(
        next_state,
        AgentEventType.NODE_COMPLETED,
        AgentEventStatus.COMPLETED,
        message,
        node=node,
    )
    return started, completed


def create_nodes(
    settings: RetrievalSettings,
    retriever: KnowledgeRetriever,
    authorization: AuthorizationService,
    memory: ConversationMemoryService,
) -> dict[str, object]:
    def guarded(
        node_name: str, node: Callable[[GraphState], Awaitable[dict[str, object]]]
    ) -> Callable[[GraphState], Awaitable[dict[str, object]]]:
        async def run(state: GraphState) -> dict[str, object]:
            if state.get("execution_step_count", 0) >= state.get(
                "maximum_execution_steps", settings.graph_max_steps
            ):
                return {
                    "failure": True,
                    "errors": (
                        GraphError(
                            code="graph.step_budget_exceeded",
                            safe_message="Graph execution-step budget was exceeded.",
                            node=node_name,
                        ),
                    ),
                    "visited_nodes": (node_name,),
                }
            try:
                update = await node(state)
                update.setdefault("execution_step_count", state.get("execution_step_count", 0) + 1)
                return update
            except Exception:
                return {
                    "failure": True,
                    "errors": (
                        GraphError(
                            code=f"graph.{node_name}_failed",
                            safe_message=f"{node_name} failed safely.",
                            retryable=False,
                            node=node_name,
                        ),
                    ),
                    "visited_nodes": (node_name,),
                }

        return run

    async def initialize(state: GraphState) -> dict[str, object]:
        now = datetime.now(UTC)
        fresh_state = cast(GraphState, dict(state))
        fresh_state["activity_events"] = ()
        accepted = event(
            fresh_state,
            AgentEventType.REQUEST_ACCEPTED,
            AgentEventStatus.ACCEPTED,
            "Request accepted.",
        )
        temporary = fresh_state
        temporary["activity_events"] = (accepted,)
        started = event(
            temporary,
            AgentEventType.GRAPH_STARTED,
            AgentEventStatus.STARTED,
            "Baseline graph started.",
        )
        return {
            "processing_status": ProcessingStatus.RUNNING,
            "execution_started_at": now,
            "deadline": now + timedelta(seconds=settings.graph_timeout_seconds),
            "maximum_execution_steps": settings.graph_max_steps,
            "maximum_recursion_depth": settings.graph_max_recursion_depth,
            "execution_step_count": 1,
            "activity_events": (accepted, started),
            "visited_nodes": ("initialize_request",),
            "failure": state.get("failure", False),
        }

    async def validate_request(state: GraphState) -> dict[str, object]:
        valid = (
            not state.get("failure")
            and bool(state["user_message"].strip())
            and 1 <= state["requested_top_k"] <= 100
        )
        report = ValidationReport(
            result=ValidationResult.PASSED if valid else ValidationResult.FAILED,
            findings=(
                ValidationFinding(
                    code="graph.input.valid" if valid else "graph.input.invalid",
                    result=ValidationResult.PASSED if valid else ValidationResult.FAILED,
                    public_message="Request validation passed." if valid else "Request is invalid.",
                ),
            ),
        )
        return {
            "normalized_query": " ".join(state["user_message"].split()),
            "validation_reports": (report,),
            "failure": not valid,
            "visited_nodes": ("validate_request",),
            "activity_events": _node_events(state, "validate_request", "Request validated."),
            "execution_step_count": state.get("execution_step_count", 0) + 1,
        }

    async def classify_intent(state: GraphState) -> dict[str, object]:
        intent, complexity = classify(state["normalized_query"])
        return {
            "detected_intent": intent,
            "task_complexity": complexity,
            "visited_nodes": ("classify_intent",),
            "activity_events": _node_events(
                state, "classify_intent", f"Classified as {intent.value}."
            ),
            "execution_step_count": state.get("execution_step_count", 0) + 1,
        }

    async def load_memory(state: GraphState) -> dict[str, object]:
        started = event(
            state,
            AgentEventType.MEMORY_LOAD_STARTED,
            AgentEventStatus.STARTED,
            "Session memory load started.",
            node="load_memory",
        )
        try:
            result = await memory.load(state["session_id"], state["principal"])
        except MemoryError:
            return {
                "warnings": ("Session memory could not be loaded; continuing statelessly.",),
                "conversation_context": MemoryContext(),
                "memory_used": False,
                "memory_update_status": "load_failed",
                "activity_events": (started,),
                "visited_nodes": ("load_memory",),
            }
        snapshot = result.snapshot
        context = snapshot.context if snapshot is not None else MemoryContext()
        temporary = cast(GraphState, dict(state))
        temporary["activity_events"] = (*state.get("activity_events", ()), started)
        loaded = event(
            temporary,
            AgentEventType.MEMORY_LOADED,
            AgentEventStatus.COMPLETED,
            "Session memory loaded.",
            node="load_memory",
            payload=PublicAgentEventPayload(
                turn_count=context.turn_count,
                evidence_reference_count=(
                    snapshot.evidence_reference_count if snapshot is not None else 0
                ),
            ),
        )
        return {
            "conversation_context": context,
            "memory_used": snapshot is not None and snapshot.turn_count > 0,
            "memory_update_status": "loaded" if result.enabled else "disabled",
            "activity_events": (started, loaded),
            "visited_nodes": ("load_memory",),
        }

    async def resolve_followup_context(state: GraphState) -> dict[str, object]:
        query, detected, used = resolve_followup(
            state["original_query"],
            state.get("conversation_context", MemoryContext()),
        )
        if not memory.settings.memory_followup_context_enabled:
            query, used = state["original_query"], False
        resolved = event(
            state,
            AgentEventType.MEMORY_CONTEXT_RESOLVED,
            AgentEventStatus.COMPLETED,
            "Follow-up context evaluated.",
            node="resolve_followup_context",
            payload=PublicAgentEventPayload(context_used=used),
        )
        return {
            "resolved_query": query,
            "normalized_query": query,
            "context_reference_detected": detected,
            "context_used": used,
            "activity_events": (resolved,),
            "visited_nodes": ("resolve_followup_context",),
        }

    async def supervisor(state: GraphState) -> dict[str, object]:
        route = supervise(state["detected_intent"], state["principal"], authorization)
        route_event = event(
            state,
            AgentEventType.ROUTE_SELECTED,
            AgentEventStatus.COMPLETED,
            f"Selected {route.value} route.",
            node="supervisor",
            payload=PublicAgentEventPayload(route=route),
        )
        return {
            "selected_route": route,
            "visited_nodes": ("supervisor",),
            "activity_events": (route_event,),
            "execution_step_count": state.get("execution_step_count", 0) + 1,
        }

    async def simple_retrieval(state: GraphState) -> dict[str, object]:
        started = event(
            state,
            AgentEventType.RETRIEVAL_STARTED,
            AgentEventStatus.STARTED,
            "Authorized retrieval started.",
            node="simple_retrieval",
        )
        try:
            remaining = max(0.001, (state["deadline"] - datetime.now(UTC)).total_seconds())
            async with asyncio.timeout(remaining):
                result = await retriever.retrieve(
                    state["principal"],
                    state["normalized_query"],
                    top_k=min(state["requested_top_k"], settings.graph_max_evidence_items),
                    filters=state["retrieval_filters"],
                    request_id=str(state["request_id"]),
                    trace_id=str(state["trace_id"]),
                )
        except (RetrievalError, TimeoutError):
            return {
                "failure": True,
                "errors": (
                    GraphError(
                        code="graph.retrieval_failed",
                        safe_message="Knowledge retrieval failed safely.",
                        retryable=False,
                        node="simple_retrieval",
                    ),
                ),
                "activity_events": (started,),
                "visited_nodes": ("simple_retrieval",),
            }
        temporary = cast(GraphState, dict(state))
        temporary["activity_events"] = (*state.get("activity_events", ()), started)
        completed = event(
            temporary,
            AgentEventType.RETRIEVAL_COMPLETED,
            AgentEventStatus.COMPLETED,
            f"Retrieved {len(result.evidence)} authorized evidence items.",
            node="simple_retrieval",
            payload=PublicAgentEventPayload(result_count=len(result.evidence)),
        )
        return {
            "retrieved_evidence": result.evidence[: settings.graph_max_evidence_items],
            "warnings": result.warnings[: settings.graph_max_warnings],
            "retrieval_status": result.completion_status.value,
            "processing_status": (
                ProcessingStatus.PARTIAL_SUCCESS
                if result.completion_status.value == "partial_success"
                else ProcessingStatus.RUNNING
            ),
            "activity_events": (started, completed),
            "visited_nodes": ("simple_retrieval",),
            "execution_step_count": state.get("execution_step_count", 0) + 1,
        }

    async def validate_evidence(state: GraphState) -> dict[str, object]:
        seen: set[object] = set()
        valid = []
        rejected = 0
        allowed_levels = authorization.allowed_access_levels(state["principal"])
        role = state["principal"].identity.role
        manifest = json.loads(
            await asyncio.to_thread(settings.ingestion_manifest_path.read_text, encoding="utf-8")
        )
        expected_fingerprint = str(manifest["build_fingerprint"])
        for item in state.get("retrieved_evidence", ()):
            evidence = item.evidence
            if (
                not isinstance(evidence.chunk_id, UUID)
                or not isinstance(evidence.evidence_id, UUID)
                or evidence.chunk_id in seen
                or evidence.access_level not in allowed_levels
                or role not in evidence.allowed_roles
                or evidence.source_line_start > evidence.source_line_end
                or not math.isfinite(item.hybrid_score)
                or evidence.build_fingerprint != expected_fingerprint
            ):
                rejected += 1
                continue
            seen.add(evidence.chunk_id)
            valid.append(item)
        report = ValidationReport(
            result=ValidationResult.WARNING if rejected else ValidationResult.PASSED,
            findings=(
                ValidationFinding(
                    code="graph.evidence.valid",
                    result=ValidationResult.WARNING if rejected else ValidationResult.PASSED,
                    public_message=(
                        f"Validated {len(valid)} evidence items; rejected {rejected}."
                        if rejected
                        else f"Validated {len(valid)} evidence items."
                    ),
                ),
            ),
        )
        validation_event = event(
            state,
            AgentEventType.VALIDATION_COMPLETED,
            AgentEventStatus.COMPLETED,
            "Evidence validation completed.",
            node="validate_evidence",
            payload=PublicAgentEventPayload(result_count=len(valid)),
        )
        return {
            "retrieved_evidence": tuple(valid),
            "warnings": (
                (f"Rejected {rejected} unauthorized or malformed evidence items.",)
                if rejected
                else ()
            ),
            "validation_reports": (report,),
            "activity_events": (validation_event,),
            "visited_nodes": ("validate_evidence",),
        }

    async def direct_response(state: GraphState) -> dict[str, object]:
        return {
            "response_text": (
                "Hello. I can route authorized enterprise knowledge lookups; "
                "generative answers are not implemented."
            ),
            "visited_nodes": ("direct_response",),
            "activity_events": _node_events(
                state, "direct_response", "Prepared deterministic response."
            ),
        }

    async def deny_request(state: GraphState) -> dict[str, object]:
        return {
            "processing_status": ProcessingStatus.DENIED,
            "response_text": "Your role does not permit this operation.",
            "retrieved_evidence": (),
            "visited_nodes": ("deny_request",),
            "activity_events": _node_events(state, "deny_request", "Request denied safely."),
        }

    async def unsupported(state: GraphState) -> dict[str, object]:
        return {
            "response_text": "This capability is explicitly not implemented in the baseline graph.",
            "warnings": ("Requested capability is unavailable.",),
            "visited_nodes": ("unsupported",),
            "activity_events": _node_events(state, "unsupported", "Capability deferred."),
        }

    async def prepare_output(state: GraphState) -> dict[str, object]:
        response = state.get("response_text") or (
            "Authorized evidence was retrieved and validated. "
            "Generative answer synthesis is not implemented."
        )
        return {
            "response_text": response,
            "visited_nodes": ("prepare_output",),
            "activity_events": _node_events(state, "prepare_output", "Public output prepared."),
        }

    async def update_memory(state: GraphState) -> dict[str, object]:
        started = event(
            state,
            AgentEventType.MEMORY_UPDATE_STARTED,
            AgentEventStatus.STARTED,
            "Session memory update started.",
            node="update_memory",
        )
        status = state.get("processing_status", ProcessingStatus.RUNNING)
        effective_status = (
            ProcessingStatus.COMPLETED if status is ProcessingStatus.RUNNING else status
        )
        try:
            result = await memory.update(
                request_id=state["request_id"],
                session_id=state["session_id"],
                principal=state["principal"],
                user_message=state["original_query"],
                assistant_message=state["response_text"],
                intent=state.get("detected_intent", Intent.UNSUPPORTED),
                selected_route=state["selected_route"],
                completion_status=effective_status,
                evidence=state.get("retrieved_evidence", ()),
                warnings=state.get("warnings", ()),
                created_at=state["invocation_timestamp"],
            )
        except MemoryError:
            return {
                "warnings": ("Response completed, but session memory was not updated.",),
                "memory_update_status": "failed",
                "activity_events": (started,),
                "visited_nodes": ("update_memory",),
            }
        temporary = cast(GraphState, dict(state))
        temporary["activity_events"] = (*state.get("activity_events", ()), started)
        updated = event(
            temporary,
            AgentEventType.MEMORY_UPDATED,
            AgentEventStatus.COMPLETED,
            "Session memory update completed.",
            node="update_memory",
            payload=PublicAgentEventPayload(evicted_turn_count=result.eviction.evicted_turns),
        )
        return {
            "memory_update_status": (
                "duplicate" if result.duplicate else "stored" if result.stored else "skipped"
            ),
            "memory_eviction_count": result.eviction.evicted_turns,
            "current_turn_sequence": result.sequence_number,
            "activity_events": (started, updated),
            "visited_nodes": ("update_memory",),
        }

    async def handle_failure(state: GraphState) -> dict[str, object]:
        return {
            "processing_status": ProcessingStatus.FAILED,
            "selected_route": Route.FAILURE,
            "response_text": "The request failed safely.",
            "retrieved_evidence": (),
            "visited_nodes": ("handle_failure",),
            "activity_events": _node_events(state, "handle_failure", "Failure handled safely."),
        }

    async def finalize(state: GraphState) -> dict[str, object]:
        status = state.get("processing_status", ProcessingStatus.RUNNING)
        if status is ProcessingStatus.RUNNING:
            status = ProcessingStatus.COMPLETED
        final_event = event(
            state,
            AgentEventType.RESPONSE_FAILED
            if status is ProcessingStatus.FAILED
            else AgentEventType.RESPONSE_COMPLETED,
            AgentEventStatus.FAILED
            if status is ProcessingStatus.FAILED
            else AgentEventStatus.COMPLETED,
            "Graph execution failed."
            if status is ProcessingStatus.FAILED
            else "Graph execution completed.",
            node="finalize_execution",
        )
        output = GraphOutput(
            graph_version="1.0",
            request_id=state["request_id"],
            trace_id=state["trace_id"],
            session_id=state["session_id"],
            completion_status=status,
            selected_route=state["selected_route"],
            intent=state.get("detected_intent", Intent.UNSUPPORTED),
            evidence=tuple(
                GraphEvidenceAttribution.from_hybrid(item)
                for item in state.get("retrieved_evidence", ())
            ),
            warnings=state.get("warnings", ()),
            response_text=state.get("response_text", "The request completed without a response."),
            validation_reports=state.get("validation_reports", ()),
            agent_status=PublicAgentStatus(
                request_id=state["request_id"],
                status=status,
                node="finalize_execution",
                public_message=(
                    "Graph execution failed safely."
                    if status is ProcessingStatus.FAILED
                    else "Graph execution completed."
                ),
                route=state["selected_route"],
                recursion_depth=0,
            ),
            memory_used=state.get("memory_used", False),
            context_resolved=state.get("context_used", False),
            turn_sequence=state.get("current_turn_sequence"),
            memory_update_status=state.get("memory_update_status", "disabled"),
        )
        return {
            "processing_status": status,
            "final_output": output,
            "activity_events": (final_event,),
            "visited_nodes": ("finalize_execution",),
        }

    return {
        "initialize_request": initialize,
        "validate_request": guarded("validate_request", validate_request),
        "load_memory": guarded("load_memory", load_memory),
        "resolve_followup_context": guarded("resolve_followup_context", resolve_followup_context),
        "classify_intent": guarded("classify_intent", classify_intent),
        "supervisor": guarded("supervisor", supervisor),
        "simple_retrieval": guarded("simple_retrieval", simple_retrieval),
        "validate_evidence": guarded("validate_evidence", validate_evidence),
        "direct_response": guarded("direct_response", direct_response),
        "deny_request": guarded("deny_request", deny_request),
        "unsupported": guarded("unsupported", unsupported),
        "prepare_output": guarded("prepare_output", prepare_output),
        "update_memory": guarded("update_memory", update_memory),
        "handle_failure": handle_failure,
        "finalize_execution": finalize,
    }
