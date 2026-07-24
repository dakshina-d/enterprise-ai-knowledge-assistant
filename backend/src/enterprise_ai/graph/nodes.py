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
from enterprise_ai.graph.routing import classify, requests_inaccessible_access, supervise
from enterprise_ai.graph.schemas import GraphEvidenceAttribution, GraphOutput
from enterprise_ai.graph.state import GraphState
from enterprise_ai.llm.models import ResponseMode
from enterprise_ai.llm.response_service import GroundedResponseService
from enterprise_ai.mcp_tools.client import result_count
from enterprise_ai.mcp_tools.errors import (
    MCPAuthorizationError,
    MCPEnterpriseError,
    MCPInputError,
)
from enterprise_ai.mcp_tools.models import SERVER_NAME
from enterprise_ai.mcp_tools.service import MCPEnterpriseService, select_mcp_tool
from enterprise_ai.memory.context import resolve_followup
from enterprise_ai.memory.exceptions import MemoryError
from enterprise_ai.memory.models import MemoryContext
from enterprise_ai.memory.service import ConversationMemoryService
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import (
    AgentEvent,
    AgentEventStatus,
    AgentEventType,
    PublicAgentEventPayload,
)
from enterprise_ai.models.graph import (
    GraphError,
    Intent,
    PublicAgentStatus,
    Route,
    ValidationFinding,
    ValidationReport,
    ValidationResult,
)
from enterprise_ai.observability.tracing import RunType, SafeTracer
from enterprise_ai.research.models import ResearchRequest
from enterprise_ai.research.service import ResearchService
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.exceptions import RetrievalError
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.security.guardrails import contains_untrusted_instruction
from enterprise_ai.tools.python_analysis.service import PythonAnalysisTool, plan_analysis


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
    analysis: PythonAnalysisTool,
    responses: GroundedResponseService,
    mcp_service: MCPEnterpriseService,
    research_service: ResearchService | None = None,
    tracer: SafeTracer | None = None,
) -> dict[str, object]:
    traces = tracer or SafeTracer()
    research = research_service or ResearchService(
        settings, retriever, authorization, analysis, tracer=traces
    )

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
            trace_names: dict[str, tuple[str, RunType]] = {
                "supervisor": ("enterprise_ai.supervisor", "chain"),
                "simple_retrieval": ("enterprise_ai.retrieval", "retriever"),
                "cross_document_research": ("enterprise_ai.research", "chain"),
                "python_analysis": ("enterprise_ai.python_analysis", "tool"),
                "generate_response": ("enterprise_ai.response", "chain"),
                "validate_citations": ("enterprise_ai.citation_validation", "chain"),
                "update_memory": ("enterprise_ai.memory", "chain"),
            }
            try:
                name, run_type = trace_names.get(node_name, ("", "chain"))
                metadata = {
                    "request_id": state.get("request_id"),
                    "trace_id": state.get("trace_id"),
                    "session_id": state.get("session_id"),
                    "user_role": state["principal"].identity.role,
                    "route": state.get("selected_route"),
                    "top_k": state.get("requested_top_k"),
                    "filter_present": bool(state.get("retrieval_filters")),
                }
                if name:
                    async with traces.span(name, run_type, metadata) as span:
                        update = await node(state)
                        if span is not None:
                            retrieved = update.get("retrieved_evidence", ())
                            completion_status = update.get("processing_status")
                            if (
                                node_name == "supervisor"
                                and update.get("selected_route") is Route.DENY
                            ):
                                completion_status = ProcessingStatus.DENIED
                            enrichment = {
                                "route": update.get("selected_route"),
                                "evidence_count": (
                                    len(retrieved) if isinstance(retrieved, tuple) else 0
                                ),
                                "excluded_count": update.get("excluded_evidence_count"),
                                "citation_valid": not bool(update.get("failure")),
                                "fallback_reason": update.get("fallback_reason"),
                            }
                            if completion_status is not None:
                                enrichment["completion_status"] = completion_status
                            span.update_metadata(enrichment)
                else:
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
        route = (
            Route.DENY
            if requests_inaccessible_access(
                state["resolved_query"], state["principal"], authorization
            )
            else supervise(state["detected_intent"], state["principal"], authorization)
        )
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
                or contains_untrusted_instruction(evidence.text)
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
            state["analysis_result"].summary
            if state.get("analysis_result") is not None
            else "Authorized evidence was retrieved and validated. "
            "Generative answer synthesis is not implemented."
        )
        return {
            "response_text": response,
            "visited_nodes": ("prepare_output",),
            "activity_events": _node_events(state, "prepare_output", "Public output prepared."),
        }

    async def python_analysis(state: GraphState) -> dict[str, object]:
        authorization_started = event(
            state,
            AgentEventType.TOOL_AUTHORIZATION_STARTED,
            AgentEventStatus.STARTED,
            "Python analysis authorization started.",
            node="python_analysis",
        )
        analysis.require_authorized(state["principal"])
        temporary = cast(GraphState, dict(state))
        temporary["activity_events"] = (*state.get("activity_events", ()), authorization_started)
        authorized = event(
            temporary,
            AgentEventType.TOOL_AUTHORIZED,
            AgentEventStatus.COMPLETED,
            "Python analysis authorized.",
            node="python_analysis",
        )
        temporary["activity_events"] = (*temporary["activity_events"], authorized)
        started = event(
            temporary,
            AgentEventType.TOOL_STARTED,
            AgentEventStatus.STARTED,
            "Structured Python analysis started.",
            node="python_analysis",
        )
        request = plan_analysis(state["resolved_query"])
        result = await analysis.execute(
            state["principal"], request, request_id=state["request_id"], trace_id=state["trace_id"]
        )
        temporary["activity_events"] = (*temporary["activity_events"], started)
        completed = event(
            temporary,
            AgentEventType.TOOL_COMPLETED,
            AgentEventStatus.COMPLETED,
            "Structured Python analysis completed.",
            node="python_analysis",
            payload=PublicAgentEventPayload(result_count=len(result.items)),
        )
        return {
            "analysis_request": request,
            "analysis_result": result,
            "response_text": result.summary,
            "activity_events": (authorization_started, authorized, started, completed),
            "visited_nodes": ("python_analysis",),
        }

    async def execute_mcp_tool(state: GraphState) -> dict[str, object]:
        try:
            selection = select_mcp_tool(state["resolved_query"])
        except MCPInputError:
            failed = event(
                state,
                AgentEventType.MCP_FAILED,
                AgentEventStatus.WARNING,
                "Enterprise data request needs one exact supported service and operation.",
                node="execute_mcp_tool",
                payload=PublicAgentEventPayload(
                    route=Route.MCP_TOOL,
                    server_identifier=SERVER_NAME,
                ),
            )
            return {
                "processing_status": ProcessingStatus.PARTIAL_SUCCESS,
                "response_text": (
                    "Provide one exact fictional service name and request its profile, metrics, "
                    "or change windows."
                ),
                "activity_events": (failed,),
                "visited_nodes": ("execute_mcp_tool",),
            }
        selected_payload = PublicAgentEventPayload(
            route=Route.MCP_TOOL,
            mcp_tool_name=selection.tool_name,
            server_identifier=SERVER_NAME,
        )
        started = event(
            state,
            AgentEventType.MCP_STARTED,
            AgentEventStatus.STARTED,
            "Authorized enterprise data operation started.",
            node="execute_mcp_tool",
            payload=selected_payload,
        )
        temporary = cast(GraphState, dict(state))
        temporary["activity_events"] = (*state.get("activity_events", ()), started)
        selected = event(
            temporary,
            AgentEventType.MCP_TOOL_SELECTED,
            AgentEventStatus.COMPLETED,
            "A read-only enterprise data tool was selected.",
            node="execute_mcp_tool",
            payload=selected_payload,
        )
        try:
            execution = await mcp_service.execute(state["principal"], selection)
        except MCPAuthorizationError:
            temporary["activity_events"] = (
                *state.get("activity_events", ()),
                started,
                selected,
            )
            denied = event(
                temporary,
                AgentEventType.MCP_DENIED,
                AgentEventStatus.DENIED,
                "Enterprise data operation denied.",
                node="execute_mcp_tool",
                payload=selected_payload,
            )
            return {
                "processing_status": ProcessingStatus.DENIED,
                "response_text": "Your role does not permit this operation.",
                "activity_events": (started, selected, denied),
                "visited_nodes": ("execute_mcp_tool",),
            }
        except MCPEnterpriseError:
            temporary["activity_events"] = (
                *state.get("activity_events", ()),
                started,
                selected,
            )
            failed = event(
                temporary,
                AgentEventType.MCP_FAILED,
                AgentEventStatus.FAILED,
                "Enterprise data operation failed safely.",
                node="execute_mcp_tool",
                payload=selected_payload,
            )
            return {
                "failure": True,
                "errors": (
                    GraphError(
                        code="mcp.operation_failed",
                        safe_message="Enterprise data operation failed safely.",
                        node="execute_mcp_tool",
                    ),
                ),
                "activity_events": (started, selected, failed),
                "visited_nodes": ("execute_mcp_tool",),
            }
        temporary["activity_events"] = (
            *state.get("activity_events", ()),
            started,
            selected,
        )
        completed = event(
            temporary,
            AgentEventType.MCP_COMPLETED,
            AgentEventStatus.COMPLETED,
            "Enterprise data operation completed.",
            node="execute_mcp_tool",
            payload=selected_payload.model_copy(
                update={
                    "result_count": result_count(execution.result),
                    "duration_category": "bounded",
                }
            ),
        )
        return {
            "mcp_execution": execution,
            "response_text": execution.response_text,
            "activity_events": (started, selected, completed),
            "visited_nodes": ("execute_mcp_tool",),
        }

    async def generate_response(state: GraphState) -> dict[str, object]:
        started = event(
            state,
            AgentEventType.RESPONSE_GENERATION_STARTED,
            AgentEventStatus.STARTED,
            "Grounded response generation started.",
            node="generate_response",
        )
        if state.get("analysis_result") is not None:
            grounded = await responses.analysis_response(
                state["resolved_query"], state["analysis_result"]
            )
            update: dict[str, object] = {
                "response_mode": ResponseMode.STRUCTURED_ANALYSIS,
                "grounded_response": grounded,
                "response_text": grounded.answer_text,
                "provider_status": "completed",
                "deterministic_fallback_used": grounded.deterministic_fallback_used,
                "deterministic_analysis_rendering_used": (
                    grounded.deterministic_analysis_rendering_used
                ),
                "fallback_reason": grounded.fallback_reason,
            }
        elif state.get("research_result") is not None:
            (
                grounded,
                draft,
                validation,
                repairs,
                research_llm_calls,
            ) = await responses.research_response(
                state["resolved_query"],
                state.get("retrieved_evidence", ()),
                state["principal"],
                state["research_result"],
            )
            update = {
                "response_mode": ResponseMode.GROUNDED_RETRIEVAL,
                "grounded_response": grounded,
                "grounded_answer_draft": draft,
                "citation_validation": validation,
                "response_repair_count": repairs,
                "response_text": grounded.answer_text,
                "provider_status": "completed",
                "deterministic_fallback_used": grounded.deterministic_fallback_used,
                "fallback_reason": grounded.fallback_reason,
                "research_result": state["research_result"].model_copy(
                    update={
                        "budget_usage": state["research_result"].budget_usage.model_copy(
                            update={
                                "llm_calls": (
                                    state["research_result"].budget_usage.llm_calls
                                    + research_llm_calls
                                ),
                                "exhausted": (
                                    state["research_result"].budget_usage.exhausted
                                    or research_llm_calls == 0
                                ),
                            }
                        )
                    }
                ),
            }
        else:
            grounded, draft, validation, repairs = await responses.retrieval_response(
                state["resolved_query"], state.get("retrieved_evidence", ()), state["principal"]
            )
            update = {
                "response_mode": ResponseMode.GROUNDED_RETRIEVAL,
                "grounded_response": grounded,
                "grounded_answer_draft": draft,
                "citation_validation": validation,
                "response_repair_count": repairs,
                "response_text": grounded.answer_text,
                "provider_status": "completed",
                "deterministic_fallback_used": grounded.deterministic_fallback_used,
                "fallback_reason": grounded.fallback_reason,
            }
        temporary = cast(GraphState, dict(state))
        temporary["activity_events"] = (*state.get("activity_events", ()), started)
        response_events: list[AgentEvent] = [started]
        if grounded.fallback_reason is not None:
            fallback_used = event(
                temporary,
                AgentEventType.RESPONSE_FALLBACK_USED,
                AgentEventStatus.WARNING,
                "A safe deterministic response was used.",
                node="generate_response",
                payload=PublicAgentEventPayload(error_code=grounded.fallback_reason.value),
            )
            response_events.append(fallback_used)
            temporary["activity_events"] = (
                *state.get("activity_events", ()),
                *response_events,
            )
        completed = event(
            temporary,
            AgentEventType.RESPONSE_GENERATION_COMPLETED,
            AgentEventStatus.COMPLETED,
            "Grounded response generation completed.",
            node="generate_response",
        )
        update.update(
            {
                "activity_events": (*response_events, completed),
                "visited_nodes": ("generate_response",),
            }
        )
        return update

    async def cross_document_research(state: GraphState) -> dict[str, object]:
        if not settings.research_enabled:
            return {
                "failure": True,
                "errors": (
                    GraphError(
                        code="research.disabled",
                        safe_message="Research is disabled.",
                        node="cross_document_research",
                    ),
                ),
                "visited_nodes": ("cross_document_research",),
            }
        research_events: list[AgentEvent] = []
        temporary = cast(GraphState, dict(state))

        def emit(
            kind: AgentEventType,
            message: str,
            payload: PublicAgentEventPayload,
            status: AgentEventStatus = AgentEventStatus.COMPLETED,
        ) -> None:
            temporary["activity_events"] = (
                *state.get("activity_events", ()),
                *research_events,
            )
            research_events.append(
                event(
                    temporary,
                    kind,
                    status,
                    message,
                    node="cross_document_research",
                    payload=payload,
                )
            )

        empty_payload = PublicAgentEventPayload()
        emit(
            AgentEventType.RESEARCH_STARTED,
            "Research started.",
            empty_payload,
            AgentEventStatus.STARTED,
        )
        emit(
            AgentEventType.RESEARCH_PLANNING_STARTED,
            "Research planning started.",
            empty_payload,
            AgentEventStatus.STARTED,
        )
        try:
            result = await asyncio.wait_for(
                research.run(
                    ResearchRequest(
                        question=state["resolved_query"],
                        principal=state["principal"],
                        request_id=state["request_id"],
                        trace_id=state["trace_id"],
                        session_id=state["session_id"],
                    )
                ),
                timeout=min(
                    settings.research_max_execution_seconds,
                    max(0.1, (state["deadline"] - datetime.now(UTC)).total_seconds()),
                ),
            )
        except Exception:
            emit(
                AgentEventType.RESEARCH_FAILED,
                "Research failed safely.",
                empty_payload,
                AgentEventStatus.FAILED,
            )
            return {
                "failure": True,
                "errors": (
                    GraphError(
                        code="research.execution_failed",
                        safe_message="Research failed safely.",
                        node="cross_document_research",
                    ),
                ),
                "visited_nodes": ("cross_document_research",),
                "activity_events": tuple(research_events),
            }
        evidence = tuple(entry.evidence for entry in result.evidence_ledger.entries)
        warnings = list(result.warnings)
        warnings.extend(f"Research gap: {gap.dimension}" for gap in result.gaps)
        warnings.extend(conflict.description for conflict in result.conflicts)
        plan_payload = PublicAgentEventPayload(plan_id=result.plan.plan_id)
        emit(
            AgentEventType.RESEARCH_CATALOG_COMPLETED, "Authorized catalog completed.", plan_payload
        )
        emit(AgentEventType.RESEARCH_PLAN_CREATED, "Research plan created.", plan_payload)
        emit(AgentEventType.RESEARCH_PLAN_VALIDATED, "Research plan validated.", plan_payload)
        for worker_result in result.worker_results:
            payload = PublicAgentEventPayload(
                plan_id=result.plan.plan_id,
                task_id=worker_result.task_id,
                parent_task_id=worker_result.parent_task_id,
                depth=worker_result.depth,
                round_number=worker_result.depth,
                evidence_count=len(worker_result.evidence),
            )
            emit(AgentEventType.RESEARCH_WORKER_DISPATCHED, "Research worker dispatched.", payload)
            emit(
                AgentEventType.RESEARCH_WORKER_STARTED,
                "Research worker started.",
                payload,
                AgentEventStatus.STARTED,
            )
            emit(
                AgentEventType.RESEARCH_RETRIEVAL_COMPLETED,
                "Research retrieval completed.",
                payload,
            )
            if worker_result.analysis_result is not None:
                emit(
                    AgentEventType.RESEARCH_ANALYSIS_COMPLETED,
                    "Research analysis completed.",
                    payload,
                )
            emit(
                AgentEventType.RESEARCH_WORKER_FAILED
                if worker_result.error_category
                else AgentEventType.RESEARCH_WORKER_COMPLETED,
                "Research worker failed safely."
                if worker_result.error_category
                else "Research worker completed.",
                payload,
                AgentEventStatus.FAILED
                if worker_result.error_category
                else AgentEventStatus.COMPLETED,
            )
        summary_payload = PublicAgentEventPayload(
            plan_id=result.plan.plan_id,
            worker_count=len(result.worker_results),
            evidence_count=len(result.evidence_ledger.entries),
            gap_count=len(result.gaps),
            conflict_count=len(result.conflicts),
        )
        emit(AgentEventType.RESEARCH_ROUND_COMPLETED, "Research rounds completed.", summary_payload)
        if any(item.depth for item in result.worker_results):
            emit(
                AgentEventType.RESEARCH_CHILD_TASKS_CREATED,
                "Research child tasks completed.",
                summary_payload,
            )
        emit(
            AgentEventType.RESEARCH_AGGREGATION_COMPLETED,
            "Research aggregation completed.",
            summary_payload,
        )
        emit(
            AgentEventType.RESEARCH_COVERAGE_ASSESSED,
            "Research coverage assessed.",
            summary_payload,
        )
        if result.budget_usage.exhausted:
            emit(
                AgentEventType.RESEARCH_BUDGET_EXHAUSTED,
                "Research budget exhausted.",
                summary_payload,
                AgentEventStatus.WARNING,
            )
        partial_research = result.coverage.status.value in {
            "partially_sufficient",
            "insufficient",
            "blocked_by_authorization",
            "budget_exhausted",
        }
        failed_research = result.coverage.status.value == "failed"
        if (result.warnings or result.gaps or partial_research) and not failed_research:
            emit(
                AgentEventType.RESEARCH_PARTIAL,
                "Research completed with limitations.",
                summary_payload,
                AgentEventStatus.WARNING,
            )
        if failed_research:
            emit(
                AgentEventType.RESEARCH_FAILED,
                "Research failed safely.",
                summary_payload,
                AgentEventStatus.FAILED,
            )
        elif not partial_research:
            emit(AgentEventType.RESEARCH_COMPLETED, "Research completed.", summary_payload)
        return {
            "research_result": result,
            "retrieved_evidence": evidence,
            "retrieval_status": result.coverage.status.value,
            "warnings": tuple(warnings),
            "visited_nodes": ("cross_document_research",),
            "activity_events": tuple(research_events),
            "failure": failed_research,
        }

    async def validate_response_citations(state: GraphState) -> dict[str, object]:
        started = event(
            state,
            AgentEventType.CITATION_VALIDATION_STARTED,
            AgentEventStatus.STARTED,
            "Citation validation started.",
            node="validate_citations",
        )
        validation = state.get("citation_validation")
        valid = (
            validation is None
            or validation.valid
            or state["grounded_response"].deterministic_fallback_used
        )
        completed = event(
            cast(
                GraphState,
                {**state, "activity_events": (*state.get("activity_events", ()), started)},
            ),
            AgentEventType.CITATION_VALIDATION_COMPLETED
            if valid
            else AgentEventType.CITATION_VALIDATION_FAILED,
            AgentEventStatus.COMPLETED if valid else AgentEventStatus.FAILED,
            "Citation validation completed." if valid else "Citation validation failed safely.",
            node="validate_citations",
        )
        return {
            "failure": not valid,
            "activity_events": (started, completed),
            "visited_nodes": ("validate_citations",),
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
            graph_version="1.2",
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
            analysis_result=state.get("analysis_result"),
            citations=(
                state["grounded_response"].citations if state.get("grounded_response") else ()
            ),
            response_provider=(
                state["grounded_response"].provider if state.get("grounded_response") else None
            ),
            response_model=(
                state["grounded_response"].model if state.get("grounded_response") else None
            ),
            deterministic_fallback_used=state.get("deterministic_fallback_used", False),
            deterministic_analysis_rendering_used=state.get(
                "deterministic_analysis_rendering_used", False
            ),
            fallback_reason=state.get("fallback_reason"),
            insufficient_evidence=(
                state["grounded_response"].insufficient_evidence
                if state.get("grounded_response")
                else False
            ),
            mcp_result=state.get("mcp_execution"),
            mcp_provenance=(
                state["mcp_execution"].provenance if state.get("mcp_execution") else None
            ),
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
        "python_analysis": guarded("python_analysis", python_analysis),
        "execute_mcp_tool": guarded("execute_mcp_tool", execute_mcp_tool),
        "cross_document_research": guarded("cross_document_research", cross_document_research),
        "generate_response": guarded("generate_response", generate_response),
        "validate_citations": guarded("validate_citations", validate_response_citations),
        "prepare_output": guarded("prepare_output", prepare_output),
        "update_memory": guarded("update_memory", update_memory),
        "handle_failure": handle_failure,
        "finalize_execution": finalize,
    }
