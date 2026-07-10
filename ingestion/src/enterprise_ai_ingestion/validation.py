"""Generated-record, citation, RBAC, and artifact validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast
from uuid import UUID

from pydantic import ValidationError

from enterprise_ai_ingestion.artifacts import MANAGED_ARTIFACTS
from enterprise_ai_ingestion.config import IngestionConfig
from enterprise_ai_ingestion.exceptions import ArtifactValidationError
from enterprise_ai_ingestion.models import (
    ChunkRecord,
    DocumentRecord,
    IngestionManifest,
    IngestionValidationReport,
    ParsedDocument,
)
from enterprise_ai_ingestion.normalizer import normalize_body


def validate_records(
    parsed: tuple[ParsedDocument, ...],
    documents: tuple[DocumentRecord, ...],
    chunks: tuple[ChunkRecord, ...],
    config: IngestionConfig,
) -> IngestionValidationReport:
    errors: list[str] = []
    source_by_id = {item.source.metadata.document_id: item for item in parsed}
    document_by_id = {item.document_id: item for item in documents}
    chunk_ids: set[UUID] = set()
    evidence_ids: set[UUID] = set()
    if len(source_by_id) != len(parsed) or len(document_by_id) != len(documents):
        errors.append("duplicate document identity")
    for document in documents:
        source = source_by_id.get(document.document_id)
        if source is None:
            errors.append("document record has no source")
            continue
        related_chunks = [chunk for chunk in chunks if chunk.document_id == document.document_id]
        if not related_chunks or document.chunk_count != len(related_chunks):
            errors.append("document chunk count is invalid")
        if document.original_content_hash != source.source.original_content_hash:
            errors.append("document original hash mismatch")
        if document.normalized_content_hash != source.normalized_content_hash:
            errors.append("document normalized hash mismatch")
    for chunk in chunks:
        source = source_by_id.get(chunk.document_id)
        chunk_document_record = document_by_id.get(chunk.document_id)
        if source is None or chunk_document_record is None:
            errors.append("chunk attribution is invalid")
            continue
        if chunk.chunk_id in chunk_ids or chunk.evidence_id in evidence_ids:
            errors.append("chunk or evidence identity is duplicated")
        chunk_ids.add(chunk.chunk_id)
        evidence_ids.add(chunk.evidence_id)
        if hashlib.sha256(chunk.text.encode("utf-8")).hexdigest() != chunk.chunk_content_hash:
            errors.append("chunk content hash mismatch")
        if chunk.approximate_token_count > config.maximum_chunk_tokens:
            errors.append("chunk exceeds maximum token count")
        if chunk.source_line_start > chunk.source_line_end:
            errors.append("chunk source line range is invalid")
        if (
            chunk.access_level != chunk_document_record.access_level
            or chunk.allowed_roles != chunk_document_record.allowed_roles
            or chunk.department != chunk_document_record.department
            or chunk.document_type != chunk_document_record.document_type
            or chunk.status != chunk_document_record.status
            or chunk.version != chunk_document_record.version
            or chunk.owner != chunk_document_record.owner
            or chunk.related_document_ids != chunk_document_record.related_document_ids
        ):
            errors.append("chunk metadata does not exactly inherit document metadata")
        if not _citation_region_contains(chunk, source):
            errors.append("chunk citation text is outside its source line range")
    for document_id in document_by_id:
        indexes = sorted(chunk.chunk_index for chunk in chunks if chunk.document_id == document_id)
        if indexes != list(range(len(indexes))):
            errors.append("chunk indexes are not contiguous")
    if errors:
        raise ArtifactValidationError("; ".join(sorted(set(errors))))
    return IngestionValidationReport(
        valid=True,
        document_count=len(documents),
        chunk_count=len(chunks),
        evidence_count=len(evidence_ids),
    )


def _citation_region_contains(chunk: ChunkRecord, source: ParsedDocument) -> bool:
    lines = source.source.original_body.splitlines()
    relative_start = chunk.source_line_start - source.source.body_source_line_start
    relative_end = chunk.source_line_end - source.source.body_source_line_start + 1
    if relative_start < 0 or relative_end > len(lines):
        return False
    region = "\n".join(lines[relative_start:relative_end])
    normalized, _ = normalize_body(region, source_line_start=chunk.source_line_start)
    return all(not line.strip() or line.strip() in normalized for line in chunk.text.splitlines())


def validate_artifacts(output_root: Path) -> IngestionValidationReport:
    missing = [name for name in MANAGED_ARTIFACTS if not (output_root / name).is_file()]
    if missing:
        raise ArtifactValidationError("generated artifacts are missing")
    try:
        documents = _read_jsonl(output_root / "documents.jsonl", DocumentRecord)
        chunks = _read_jsonl(output_root / "chunks.jsonl", ChunkRecord)
        manifest = IngestionManifest.model_validate_json(
            (output_root / "ingestion_manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ArtifactValidationError("generated artifacts are malformed") from error
    if manifest.document_count != len(documents) or manifest.chunk_count != len(chunks):
        raise ArtifactValidationError("artifact manifest counts do not match records")
    for descriptor in manifest.artifacts:
        path = output_root / descriptor.filename
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != descriptor.sha256:
            raise ArtifactValidationError("artifact hash mismatch")
    if any(
        "\\" in record.source_file or Path(record.source_file).is_absolute() for record in documents
    ):
        raise ArtifactValidationError("generated artifact contains a non-portable path")
    return IngestionValidationReport(
        valid=True,
        document_count=len(documents),
        chunk_count=len(chunks),
        evidence_count=len({chunk.evidence_id for chunk in chunks}),
    )


def _read_jsonl[ModelType: DocumentRecord | ChunkRecord](
    path: Path, model: type[ModelType]
) -> tuple[ModelType, ...]:
    records: list[ModelType] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        records.append(cast(ModelType, model.model_validate_json(line)))
    return tuple(records)
