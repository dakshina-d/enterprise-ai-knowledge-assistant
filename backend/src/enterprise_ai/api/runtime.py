"""Application-lifecycle construction for the shared graph runtime."""

from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.dependencies import KnowledgeRetriever, OfflineSparseAdapter
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.llm.dependencies import create_response_service
from enterprise_ai.memory.dependencies import create_memory_service
from enterprise_ai.observability.tracing import create_tracer
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.dense_retriever import DenseRetrievalService
from enterprise_ai.retrieval.embeddings import (
    EmbeddingProvider,
    PineconeInferenceEmbeddingProvider,
)
from enterprise_ai.retrieval.hybrid.retriever import HybridRetrievalService
from enterprise_ai.retrieval.pinecone_client import PineconeGateway, PineconeSdkGateway
from enterprise_ai.retrieval.sparse.retriever import SparseRetrievalService


def create_api_retriever(
    settings: RetrievalSettings,
    *,
    gateway: PineconeGateway | None = None,
    embeddings: EmbeddingProvider | None = None,
) -> KnowledgeRetriever:
    """Select the configured authenticated retrieval stack for FastAPI chat."""

    sparse = SparseRetrievalService(settings)
    if settings.retrieval_mode == "sparse":
        return OfflineSparseAdapter(sparse)
    settings.require_enabled()
    selected_gateway = gateway or PineconeSdkGateway(settings)
    selected_embeddings = embeddings or PineconeInferenceEmbeddingProvider(
        selected_gateway,
        settings.pinecone_dense_model,
        selected_dimension=settings.pinecone_dense_dimension,
        metric=settings.pinecone_metric,
        maximum_input_chars=settings.pinecone_max_embedding_input_chars,
    )
    dense = DenseRetrievalService(settings, selected_embeddings, selected_gateway)
    return HybridRetrievalService(settings, dense, sparse)


def create_api_runtime(
    settings: RetrievalSettings | None = None,
    *,
    gateway: PineconeGateway | None = None,
    embeddings: EmbeddingProvider | None = None,
) -> GraphRuntime:
    """Create the process-owned graph stack selected by runtime configuration."""

    active = settings or RetrievalSettings()
    tracer = create_tracer(active)
    memory = create_memory_service(active)
    responses = create_response_service(active, tracer)
    retriever = create_api_retriever(active, gateway=gateway, embeddings=embeddings)
    graph = build_graph(
        active,
        retriever,
        checkpointer=create_checkpointer(),
        memory=memory,
        responses=responses,
        tracer=tracer,
    )
    return GraphRuntime(
        graph,
        active,
        memory,
        responses,
        tracer,
        retriever_resource=retriever,
    )
