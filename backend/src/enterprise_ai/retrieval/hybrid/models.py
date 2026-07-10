"""Typed transparent hybrid retrieval results."""

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_ai.retrieval.dense_retriever import DenseEvidence


class CompletionStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL_SUCCESS = "partial_success"


class HybridEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence: DenseEvidence
    raw_dense_score: float | None = None
    raw_sparse_score: float | None = None
    normalized_dense_score: Annotated[float, Field(ge=0, le=1)] = 0
    normalized_sparse_score: Annotated[float, Field(ge=0, le=1)] = 0
    hybrid_score: Annotated[float, Field(ge=0, le=1)]
    dense_rank: int | None = None
    sparse_rank: int | None = None
    final_rank: Annotated[int, Field(ge=1)]
    retrieval_modes: frozenset[str]

    @property
    def document_id(self) -> UUID:
        return self.evidence.document_id

    @property
    def source_file(self) -> str:
        return self.evidence.source_file


class HybridRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence: tuple[HybridEvidence, ...]
    completion_status: CompletionStatus
    warnings: tuple[str, ...] = ()
    failed_branches: tuple[str, ...] = ()
    request_id: str | None = None
    trace_id: str | None = None
    dropped_unauthorized: int = 0
    malformed_results: int = 0
