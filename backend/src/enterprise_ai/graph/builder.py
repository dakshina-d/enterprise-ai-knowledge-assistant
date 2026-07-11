"""Compile and describe the baseline LangGraph topology."""

from collections.abc import Callable
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from enterprise_ai.graph.dependencies import KnowledgeRetriever
from enterprise_ai.graph.nodes import create_nodes
from enterprise_ai.graph.routing import ROUTE_NODE
from enterprise_ai.graph.schemas import GraphTopology
from enterprise_ai.graph.state import GraphState
from enterprise_ai.memory.dependencies import create_memory_service
from enterprise_ai.memory.service import ConversationMemoryService
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.tools.python_analysis.service import PythonAnalysisTool


def _after_validation(state: GraphState) -> str:
    return "handle_failure" if state.get("failure") else "load_memory"


def _after_retrieval(state: GraphState) -> str:
    return "handle_failure" if state.get("failure") else "validate_evidence"


def _selected_route(state: GraphState) -> str:
    if state.get("failure"):
        return "handle_failure"
    return ROUTE_NODE[state["selected_route"]]


def _after_operation(next_node: str) -> Callable[[GraphState], str]:
    def route(state: GraphState) -> str:
        return "handle_failure" if state.get("failure") else next_node

    return route


def build_graph(
    settings: RetrievalSettings,
    retriever: KnowledgeRetriever,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    authorization: AuthorizationService | None = None,
    memory: ConversationMemoryService | None = None,
    analysis: PythonAnalysisTool | None = None,
) -> Any:  # noqa: ANN401 - LangGraph's compiled generic is not a stable public contract.
    """Build a real asynchronous StateGraph with injected infrastructure."""
    graph = StateGraph(GraphState)
    for name, node in create_nodes(
        settings,
        retriever,
        authorization or AuthorizationService(),
        memory or create_memory_service(settings),
        analysis or PythonAnalysisTool(settings),
    ).items():
        graph.add_node(name, cast(Any, node))

    graph.add_edge(START, "initialize_request")
    graph.add_edge("initialize_request", "validate_request")
    graph.add_conditional_edges(
        "validate_request",
        _after_validation,
        {name: name for name in ("handle_failure", "load_memory")},
    )
    graph.add_conditional_edges(
        "load_memory",
        _after_operation("resolve_followup_context"),
        {name: name for name in ("handle_failure", "resolve_followup_context")},
    )
    graph.add_conditional_edges(
        "resolve_followup_context",
        _after_operation("classify_intent"),
        {name: name for name in ("handle_failure", "classify_intent")},
    )
    graph.add_conditional_edges(
        "classify_intent",
        _after_operation("supervisor"),
        {name: name for name in ("handle_failure", "supervisor")},
    )
    graph.add_conditional_edges(
        "supervisor",
        _selected_route,
        {name: name for name in {*ROUTE_NODE.values(), "handle_failure"}},
    )
    graph.add_conditional_edges(
        "simple_retrieval",
        _after_retrieval,
        {name: name for name in ("handle_failure", "validate_evidence")},
    )
    graph.add_conditional_edges(
        "validate_evidence",
        _after_operation("prepare_output"),
        {name: name for name in ("handle_failure", "prepare_output")},
    )
    for node in ("direct_response", "deny_request", "unsupported", "python_analysis"):
        graph.add_conditional_edges(
            node,
            _after_operation("prepare_output"),
            {name: name for name in ("handle_failure", "prepare_output")},
        )
    graph.add_conditional_edges(
        "prepare_output",
        _after_operation("update_memory"),
        {name: name for name in ("handle_failure", "update_memory")},
    )
    graph.add_conditional_edges(
        "update_memory",
        _after_operation("finalize_execution"),
        {name: name for name in ("handle_failure", "finalize_execution")},
    )
    graph.add_edge("handle_failure", "finalize_execution")
    graph.add_edge("finalize_execution", END)
    return graph.compile(checkpointer=checkpointer)


def describe_graph() -> GraphTopology:
    return GraphTopology(
        graph_version="1.0",
        entry_point="initialize_request",
        nodes=(
            "initialize_request",
            "validate_request",
            "load_memory",
            "resolve_followup_context",
            "classify_intent",
            "supervisor",
            "simple_retrieval",
            "validate_evidence",
            "direct_response",
            "deny_request",
            "unsupported",
            "python_analysis",
            "prepare_output",
            "update_memory",
            "handle_failure",
            "finalize_execution",
        ),
        edges=(
            ("START", "initialize_request"),
            ("initialize_request", "validate_request"),
            ("handle_failure", "finalize_execution"),
            ("finalize_execution", "END"),
        ),
        conditional_routes={
            **{f"supervisor.{route.value}": node for route, node in ROUTE_NODE.items()},
            "validate_request.ok": "load_memory",
            "validate_request.failure": "handle_failure",
            "load_memory.ok": "resolve_followup_context",
            "load_memory.failure": "handle_failure",
            "resolve_followup_context.ok": "classify_intent",
            "resolve_followup_context.failure": "handle_failure",
            "classify_intent.ok": "supervisor",
            "classify_intent.failure": "handle_failure",
            "simple_retrieval.ok": "validate_evidence",
            "simple_retrieval.failure": "handle_failure",
            "validate_evidence.ok": "prepare_output",
            "validate_evidence.failure": "handle_failure",
            "direct_response.ok": "prepare_output",
            "deny_request.ok": "prepare_output",
            "unsupported.ok": "prepare_output",
            "python_analysis.ok": "prepare_output",
            "python_analysis.failure": "handle_failure",
            "prepare_output.ok": "update_memory",
            "prepare_output.failure": "handle_failure",
            "update_memory.ok": "finalize_execution",
            "update_memory.failure": "handle_failure",
        },
        terminal_nodes=("finalize_execution",),
        implemented_capabilities=(
            "deterministic classification",
            "RBAC routing",
            "sparse retrieval",
            "public events",
            "bounded session conversational memory",
            "restricted structured Python analysis",
        ),
        planned_capabilities=(
            "LLM synthesis",
            "recursive research",
            "MCP tools",
            "durable checkpoints",
            "durable distributed conversation memory",
        ),
    )
