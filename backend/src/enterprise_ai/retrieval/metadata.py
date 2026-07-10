"""Flat, validated Pinecone metadata mapping for ingestion chunks."""

import json
from datetime import date

from enterprise_ai_ingestion.models import ChunkRecord

from enterprise_ai.retrieval.exceptions import RetrievalValidationError

type MetadataValue = str | float | bool | list[str]
type PineconeMetadata = dict[str, MetadataValue]

REQUIRED_RESULT_FIELDS = frozenset(
    {
        "chunk_id",
        "evidence_id",
        "document_id",
        "title",
        "source",
        "source_file",
        "department",
        "document_type",
        "access_level",
        "allowed_roles",
        "updated_date",
        "version",
        "status",
        "section",
        "section_path",
        "source_line_start",
        "source_line_end",
        "text",
        "chunk_content_hash",
        "build_fingerprint",
    }
)


def epoch_day(value: date) -> int:
    return (value - date(1970, 1, 1)).days


def chunk_metadata(
    chunk: ChunkRecord, *, build_fingerprint: str, maximum_bytes: int
) -> PineconeMetadata:
    metadata: PineconeMetadata = {
        "chunk_id": str(chunk.chunk_id),
        "evidence_id": str(chunk.evidence_id),
        "document_id": str(chunk.document_id),
        "title": chunk.title,
        "source": chunk.source,
        "source_file": chunk.source_file,
        "department": chunk.department,
        "document_type": chunk.document_type.value,
        "access_level": chunk.access_level.value,
        "allowed_roles": [role.value for role in chunk.allowed_roles],
        "created_date": chunk.created_date.isoformat(),
        "created_day": float(epoch_day(chunk.created_date)),
        "updated_date": chunk.updated_date.isoformat(),
        "updated_day": float(epoch_day(chunk.updated_date)),
        "version": chunk.version,
        "owner": chunk.owner,
        "status": chunk.status,
        "tags": list(chunk.tags),
        "related_document_ids": [str(value) for value in chunk.related_document_ids],
        "section": chunk.section,
        "section_path": list(chunk.section_path),
        "source_line_start": float(chunk.source_line_start),
        "source_line_end": float(chunk.source_line_end),
        "text": chunk.text,
        "search_text": chunk.search_text,
        "approximate_token_count": float(chunk.approximate_token_count),
        "chunk_content_hash": chunk.chunk_content_hash,
        "original_document_hash": chunk.original_document_hash,
        "normalized_document_hash": chunk.normalized_document_hash,
        "content_trust": chunk.content_trust.value,
        "build_fingerprint": build_fingerprint,
        "chunk_schema_version": chunk.schema_version,
    }
    if any(isinstance(value, dict) for value in metadata.values()):
        raise RetrievalValidationError("nested Pinecone metadata is not allowed")
    size = len(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode())
    if size > maximum_bytes:
        raise RetrievalValidationError("Pinecone metadata exceeds configured maximum")
    return metadata
