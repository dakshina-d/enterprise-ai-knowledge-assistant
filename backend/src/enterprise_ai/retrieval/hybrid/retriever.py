"""Concurrent dense and sparse retrieval with explicit partial results."""

import asyncio
from typing import Protocol

from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.dense_retriever import DenseEvidence, DenseRetrievalResult
from enterprise_ai.retrieval.exceptions import (
    RetrievalAuthorizationError,
    RetrievalDependencyError,
)
from enterprise_ai.retrieval.filters import DenseQueryFilters
from enterprise_ai.retrieval.hybrid.fusion import fuse
from enterprise_ai.retrieval.hybrid.models import (
    CompletionStatus,
    HybridRetrievalResult,
)
from enterprise_ai.retrieval.sparse.retriever import SparseEvidence, SparseRetrievalResult


class DenseBranch(Protocol):
    async def retrieve(
        self,
        principal: AuthenticatedPrincipal,
        query: str,
        *,
        top_k: int | None = None,
        filters: DenseQueryFilters | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> DenseRetrievalResult: ...


class SparseBranch(Protocol):
    async def retrieve(
        self,
        principal: AuthenticatedPrincipal,
        query: str,
        *,
        top_k: int | None = None,
        filters: DenseQueryFilters | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> SparseRetrievalResult: ...


class HybridRetrievalService:
    def __init__(
        self, settings: RetrievalSettings, dense: DenseBranch, sparse: SparseBranch
    ) -> None:
        self.settings, self.dense, self.sparse = settings, dense, sparse

    async def retrieve(
        self,
        principal: AuthenticatedPrincipal,
        query: str,
        *,
        top_k: int = 10,
        filters: DenseQueryFilters | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> HybridRetrievalResult:
        if not 1 <= top_k <= 100:
            raise ValueError("hybrid top-k is invalid")
        overfetch = min(
            top_k * self.settings.hybrid_overfetch_factor, self.settings.hybrid_max_candidates
        )

        async def dense_call() -> DenseRetrievalResult:
            async with asyncio.timeout(self.settings.hybrid_dense_timeout_seconds):
                return await self.dense.retrieve(
                    principal,
                    query,
                    top_k=overfetch,
                    filters=filters,
                    request_id=request_id,
                    trace_id=trace_id,
                )

        async def sparse_call() -> SparseRetrievalResult:
            async with asyncio.timeout(self.settings.hybrid_sparse_timeout_seconds):
                return await self.sparse.retrieve(
                    principal,
                    query,
                    top_k=overfetch,
                    filters=filters,
                    request_id=request_id,
                    trace_id=trace_id,
                )

        dense_result, sparse_result = await asyncio.gather(
            dense_call(), sparse_call(), return_exceptions=True
        )
        for branch_result in (dense_result, sparse_result):
            if isinstance(branch_result, asyncio.CancelledError):
                raise branch_result
            if isinstance(branch_result, RetrievalAuthorizationError):
                raise branch_result
        failures: list[str] = []
        dense_evidence: tuple[DenseEvidence, ...]
        sparse_evidence: tuple[SparseEvidence, ...]
        if isinstance(dense_result, BaseException):
            failures.append("dense")
            dense_evidence = ()
        else:
            dense_evidence = dense_result.evidence
        if isinstance(sparse_result, BaseException):
            failures.append("sparse")
            sparse_evidence = ()
        else:
            sparse_evidence = sparse_result.evidence
        if len(failures) == 2 or (failures and not self.settings.hybrid_allow_partial_results):
            raise RetrievalDependencyError("hybrid retrieval branches failed safely")
        evidence = fuse(
            dense_evidence,
            sparse_evidence,
            dense_weight=self.settings.hybrid_dense_weight,
            sparse_weight=self.settings.hybrid_sparse_weight,
            top_k=top_k,
        )
        return HybridRetrievalResult(
            evidence=evidence,
            completion_status=(
                CompletionStatus.PARTIAL_SUCCESS if failures else CompletionStatus.COMPLETE
            ),
            warnings=("One retrieval branch failed; safe partial results returned.",)
            if failures
            else (),
            failed_branches=tuple(failures),
            request_id=request_id,
            trace_id=trace_id,
        )
