"""Strongly typed source, parsing, chunk, and artifact contracts."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated
from uuid import UUID

from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.models.retrieval import DocumentType
from pydantic import BaseModel, ConfigDict, Field, model_validator


class IngestionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentTrust(StrEnum):
    UNTRUSTED_EXTERNAL_CONTENT = "untrusted_external_content"


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    BLOCKQUOTE = "blockquote"
    CODE_FENCE = "code_fence"


class SourceDocumentMetadata(IngestionModel):
    document_id: UUID
    title: Annotated[str, Field(min_length=1, max_length=500)]
    source: Annotated[str, Field(min_length=1, max_length=2_048)]
    department: Annotated[str, Field(min_length=1, max_length=200)]
    document_type: DocumentType
    access_level: AccessLevel
    allowed_roles: tuple[UserRole, ...] = Field(min_length=1)
    created_date: date
    updated_date: date
    version: Annotated[str, Field(min_length=1, max_length=100)]
    owner: Annotated[str, Field(min_length=1, max_length=300)]
    status: Annotated[str, Field(min_length=1, max_length=100)]
    tags: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...]
    related_document_ids: tuple[UUID, ...]

    @model_validator(mode="after")
    def validate_dates(self) -> "SourceDocumentMetadata":
        if self.updated_date < self.created_date:
            raise ValueError("updated date cannot precede created date")
        return self


class SourceDocument(IngestionModel):
    metadata: SourceDocumentMetadata
    source_file: str
    original_body: str
    original_content_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    body_source_line_start: Annotated[int, Field(ge=1)]


class MarkdownBlock(IngestionModel):
    kind: BlockKind
    text: Annotated[str, Field(min_length=1)]
    source_line_start: Annotated[int, Field(ge=1)]
    source_line_end: Annotated[int, Field(ge=1)]
    section_path: tuple[str, ...]

    @model_validator(mode="after")
    def validate_lines(self) -> "MarkdownBlock":
        if self.source_line_start > self.source_line_end:
            raise ValueError("block line start cannot exceed line end")
        return self


class MarkdownSection(IngestionModel):
    heading: str
    heading_path: tuple[str, ...]
    level: Annotated[int, Field(ge=0, le=6)]
    source_line_start: Annotated[int, Field(ge=1)]
    source_line_end: Annotated[int, Field(ge=1)]
    blocks: tuple[MarkdownBlock, ...]


class ParsedDocument(IngestionModel):
    source: SourceDocument
    normalized_body: str
    normalized_content_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    sections: tuple[MarkdownSection, ...]
    heading_paths: tuple[tuple[str, ...], ...]


class ChunkingConfig(IngestionModel):
    target_chunk_tokens: Annotated[int, Field(ge=1)]
    maximum_chunk_tokens: Annotated[int, Field(ge=1)]
    overlap_tokens: Annotated[int, Field(ge=0)]
    minimum_chunk_tokens: Annotated[int, Field(ge=1)]


class DocumentRecord(IngestionModel):
    schema_version: str
    document_id: UUID
    title: str
    source: str
    source_file: str
    department: str
    document_type: DocumentType
    access_level: AccessLevel
    allowed_roles: tuple[UserRole, ...]
    created_date: date
    updated_date: date
    version: str
    owner: str
    status: str
    tags: tuple[str, ...]
    related_document_ids: tuple[UUID, ...]
    original_content_hash: str
    normalized_content_hash: str
    approximate_word_count: Annotated[int, Field(ge=0)]
    approximate_token_count: Annotated[int, Field(ge=0)]
    heading_paths: tuple[tuple[str, ...], ...]
    chunk_count: Annotated[int, Field(ge=1)]
    content_trust: ContentTrust = ContentTrust.UNTRUSTED_EXTERNAL_CONTENT


class ChunkRecord(IngestionModel):
    schema_version: str
    chunk_id: UUID
    document_id: UUID
    chunk_index: Annotated[int, Field(ge=0)]
    evidence_id: UUID
    title: str
    source: str
    source_file: str
    department: str
    document_type: DocumentType
    access_level: AccessLevel
    allowed_roles: tuple[UserRole, ...]
    created_date: date
    updated_date: date
    version: str
    owner: str
    status: str
    tags: tuple[str, ...]
    related_document_ids: tuple[UUID, ...]
    section: str
    section_path: tuple[str, ...]
    source_line_start: Annotated[int, Field(ge=1)]
    source_line_end: Annotated[int, Field(ge=1)]
    text: Annotated[str, Field(min_length=1)]
    search_text: Annotated[str, Field(min_length=1)]
    approximate_token_count: Annotated[int, Field(ge=1)]
    overlap_token_count: Annotated[int, Field(ge=0)]
    chunk_content_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    original_document_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    normalized_document_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    content_trust: ContentTrust = ContentTrust.UNTRUSTED_EXTERNAL_CONTENT

    @model_validator(mode="after")
    def validate_lines(self) -> "ChunkRecord":
        if self.source_line_start > self.source_line_end:
            raise ValueError("chunk line start cannot exceed line end")
        return self


class ArtifactDescriptor(IngestionModel):
    filename: str
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class IngestionManifest(IngestionModel):
    ingestion_pipeline_version: str
    document_schema_version: str
    chunk_schema_version: str
    source_manifest_sha256: str
    chunking_configuration: ChunkingConfig
    tokenizer_name: str
    tokenizer_version: str
    document_count: int
    chunk_count: int
    evidence_count: int
    count_by_document_type: dict[str, int]
    count_by_department: dict[str, int]
    count_by_access_level: dict[str, int]
    artifacts: tuple[ArtifactDescriptor, ...]
    build_fingerprint: str


class IngestionValidationReport(IngestionModel):
    valid: bool
    document_count: int
    chunk_count: int
    evidence_count: int
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactBundle:
    files: dict[str, bytes]
    documents: tuple[DocumentRecord, ...]
    chunks: tuple[ChunkRecord, ...]
    manifest: IngestionManifest


@dataclass(frozen=True, slots=True)
class ManifestSource:
    entry: dict[str, object]
    path: Path
    source_file: str
