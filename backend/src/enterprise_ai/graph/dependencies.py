"""Graph-facing retrieval protocol and offline sparse adapter."""

from typing import Protocol

from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.retrieval.filters import DenseQueryFilters
from enterprise_ai.retrieval.hybrid.fusion import fuse
from enterprise_ai.retrieval.hybrid.models import (
    CompletionStatus,
    HybridRetrievalResult,
)
from enterprise_ai.retrieval.sparse.retriever import SparseRetrievalService


class KnowledgeRetriever(Protocol):
    async def retrieve(
        self,
        principal: AuthenticatedPrincipal,
        query: str,
        *,
        top_k: int,
        filters: DenseQueryFilters,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> HybridRetrievalResult: ...


class OfflineSparseAdapter:
    def __init__(self, sparse: SparseRetrievalService) -> None:
        self.sparse = sparse

    async def retrieve(
        self,
        principal: AuthenticatedPrincipal,
        query: str,
        *,
        top_k: int,
        filters: DenseQueryFilters,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> HybridRetrievalResult:
        result = await self.sparse.retrieve(
            principal,
            query,
            top_k=top_k,
            filters=filters,
            request_id=request_id,
            trace_id=trace_id,
        )
        evidence = fuse((), result.evidence, dense_weight=0, sparse_weight=1, top_k=top_k)
        return HybridRetrievalResult(
            evidence=evidence,
            completion_status=CompletionStatus.COMPLETE,
            request_id=request_id,
            trace_id=trace_id,
        )

    async def close(self) -> None:
        """Match provider-backed retriever lifecycle without owning resources."""
