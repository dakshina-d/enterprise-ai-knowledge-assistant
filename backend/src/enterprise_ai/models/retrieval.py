"""Provider-neutral retrieval, metadata, evidence, and search-plan contracts."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator

from enterprise_ai.models.common import (
    ChunkId,
    ContractModel,
    DocumentId,
    EvidenceId,
    new_identifier,
)
from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.models.validation import validate_text_length


class DocumentType(StrEnum):
    POLICY = "policy"
    ARCHITECTURE = "architecture"
    RUNBOOK = "runbook"
    INCIDENT = "incident"
    PRODUCT_SPECIFICATION = "product_specification"
    MEETING_NOTE = "meeting_note"


class DocumentMetadata(ContractModel):
    document_id: DocumentId
    title: Annotated[str, Field(min_length=1, max_length=500)]
    source: Annotated[str, Field(min_length=1, max_length=2048)]
    department: Annotated[str, Field(min_length=1, max_length=200)]
    document_type: DocumentType
    access_level: AccessLevel
    allowed_roles: frozenset[UserRole]
    created_date: date
    updated_date: date
    version: Annotated[str, Field(min_length=1, max_length=100)]
    content_hash: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{64}$")]

    @field_validator("title", "source", "department", "version")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
        return validate_text_length(value, maximum=2048)

    @model_validator(mode="after")
    def validate_dates_and_roles(self) -> Self:
        if self.updated_date < self.created_date:
            raise ValueError("updated_date cannot be before created_date")
        if not self.allowed_roles:
            raise ValueError("allowed_roles must not be empty")
        return self


class IndexedChunk(ContractModel):
    chunk_id: ChunkId
    document_id: DocumentId
    section: Annotated[str | None, Field(max_length=500)] = None
    chunk_index: Annotated[int, Field(ge=0)]
    text: Annotated[str, Field(min_length=1, max_length=32_000)]
    metadata: DocumentMetadata
    dense_score: Annotated[float | None, Field(ge=-1.0, le=1.0)] = None
    sparse_score: Annotated[float | None, Field(ge=0.0)] = None
    hybrid_score: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    rerank_score: Annotated[float | None, Field(ge=0.0, le=1.0)] = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return validate_text_length(value, maximum=32_000)

    @model_validator(mode="after")
    def validate_document_identity(self) -> Self:
        if self.document_id != self.metadata.document_id:
            raise ValueError("chunk document_id must match metadata document_id")
        return self


class MetadataFilters(ContractModel):
    departments: frozenset[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=frozenset
    )
    document_types: frozenset[DocumentType] = Field(default_factory=frozenset)
    access_levels: frozenset[AccessLevel] = Field(default_factory=frozenset)
    allowed_roles: frozenset[UserRole] = Field(default_factory=frozenset)
    created_from: date | None = None
    created_to: date | None = None
    updated_from: date | None = None
    updated_to: date | None = None

    @model_validator(mode="after")
    def validate_date_ranges(self) -> Self:
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created_from cannot be after created_to")
        if self.updated_from and self.updated_to and self.updated_from > self.updated_to:
            raise ValueError("updated_from cannot be after updated_to")
        return self


class RetrievalQuery(ContractModel):
    query: Annotated[str, Field(min_length=1, max_length=4_000)]
    filters: MetadataFilters = Field(default_factory=MetadataFilters)
    top_k: Annotated[int, Field(ge=1, le=100)] = 10
    namespace: Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")]

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        return validate_text_length(value, maximum=4_000)


class DenseSearchResult(ContractModel):
    chunk: IndexedChunk
    score: Annotated[float, Field(ge=-1.0, le=1.0)]
    rank: Annotated[int, Field(ge=1)]


class SparseSearchResult(ContractModel):
    chunk: IndexedChunk
    score: Annotated[float, Field(ge=0.0)]
    rank: Annotated[int, Field(ge=1)]


class HybridSearchResult(ContractModel):
    chunk: IndexedChunk
    dense_score: Annotated[float | None, Field(ge=-1.0, le=1.0)] = None
    sparse_score: Annotated[float | None, Field(ge=0.0)] = None
    hybrid_score: Annotated[float, Field(ge=0.0, le=1.0)]
    rerank_score: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    rank: Annotated[int, Field(ge=1)]


class EvidenceItem(ContractModel):
    evidence_id: EvidenceId = Field(default_factory=new_identifier)
    document_id: DocumentId
    chunk_id: ChunkId
    title: Annotated[str, Field(min_length=1, max_length=500)]
    source: Annotated[str, Field(min_length=1, max_length=2048)]
    section: Annotated[str | None, Field(max_length=500)] = None
    version: Annotated[str, Field(min_length=1, max_length=100)]
    content_hash: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{64}$")]
    text: Annotated[str, Field(min_length=1, max_length=32_000)]
    score: Annotated[float, Field(ge=0.0, le=1.0)]

    @field_validator("text")
    @classmethod
    def validate_evidence_text(cls, value: str) -> str:
        return validate_text_length(value, maximum=32_000)


class RetrievalResultSet(ContractModel):
    query: RetrievalQuery
    evidence: tuple[EvidenceItem, ...]
    total_candidates: Annotated[int, Field(ge=0)]
    warnings: tuple[Annotated[str, Field(max_length=500)], ...] = ()


class SearchSubtask(ContractModel):
    subtask_id: Annotated[str, Field(min_length=1, max_length=100)]
    query: Annotated[str, Field(min_length=1, max_length=4_000)]
    objective: Annotated[str, Field(min_length=1, max_length=2_000)]
    filters: MetadataFilters = Field(default_factory=MetadataFilters)

    @field_validator("query", "objective")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return validate_text_length(value, maximum=4_000)


class SearchPlan(ContractModel):
    objective: Annotated[str, Field(min_length=1, max_length=4_000)]
    subtasks: tuple[SearchSubtask, ...] = Field(min_length=1, max_length=20)
    maximum_parallelism: Annotated[int, Field(ge=1, le=4)] = 4

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, value: str) -> str:
        return validate_text_length(value, maximum=4_000)
