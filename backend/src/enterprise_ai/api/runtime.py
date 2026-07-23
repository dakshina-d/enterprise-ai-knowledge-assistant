"""Application-lifecycle construction for the shared graph runtime."""

from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.dependencies import OfflineSparseAdapter
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.llm.dependencies import create_response_service
from enterprise_ai.memory.dependencies import create_memory_service
from enterprise_ai.observability.tracing import create_tracer
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.sparse.retriever import SparseRetrievalService


def create_api_runtime(settings: RetrievalSettings | None = None) -> GraphRuntime:
    """Create the process-owned offline-safe graph stack used by HTTP delivery."""
    active = settings or RetrievalSettings()
    tracer = create_tracer(active)
    memory = create_memory_service(active)
    responses = create_response_service(active, tracer)
    graph = build_graph(
        active,
        OfflineSparseAdapter(SparseRetrievalService(active)),
        checkpointer=create_checkpointer(),
        memory=memory,
        responses=responses,
        tracer=tracer,
    )
    return GraphRuntime(graph, active, memory, responses, tracer)
