"""Async deterministic ingestion orchestration and artifact lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter

from enterprise_ai_ingestion.artifacts import canonical_json, jsonl, write_transactionally
from enterprise_ai_ingestion.chunker import chunk_document
from enterprise_ai_ingestion.config import (
    CHUNK_SCHEMA_VERSION,
    DOCUMENT_SCHEMA_VERSION,
    PIPELINE_VERSION,
    IngestionConfig,
)
from enterprise_ai_ingestion.exceptions import (
    ArtifactDriftError,
    ArtifactValidationError,
    IngestionError,
)
from enterprise_ai_ingestion.models import (
    ArtifactBundle,
    ArtifactDescriptor,
    ChunkingConfig,
    ChunkRecord,
    DocumentRecord,
    IngestionManifest,
    ParsedDocument,
)
from enterprise_ai_ingestion.parser import load_manifest, parse_source
from enterprise_ai_ingestion.tokenizer import RegexTokenEstimator, TokenEstimator
from enterprise_ai_ingestion.validation import validate_artifacts, validate_records


class IngestionPipeline:
    def __init__(
        self,
        config: IngestionConfig,
        tokenizer: TokenEstimator | None = None,
    ) -> None:
        self.config = config
        self.tokenizer = tokenizer or RegexTokenEstimator()

    async def expected_bundle(self) -> ArtifactBundle:
        sources = load_manifest(self.config)
        parsed_slots: list[ParsedDocument | None] = [None] * len(sources)
        semaphore = asyncio.Semaphore(self.config.concurrency)

        async def load_one(index: int) -> None:
            async with semaphore:
                try:
                    parsed_slots[index] = await asyncio.to_thread(
                        parse_source, sources[index], self.config
                    )
                except IngestionError as error:
                    raise type(error)(f"{sources[index].source_file}: {error}") from error

        async with asyncio.TaskGroup() as tasks:
            for index in range(len(sources)):
                tasks.create_task(load_one(index))
        if any(item is None for item in parsed_slots):
            raise ArtifactValidationError("source loading did not complete")
        parsed = tuple(item for item in parsed_slots if item is not None)
        chunks_by_document = tuple(
            chunk_document(document, self.config, self.tokenizer) for document in parsed
        )
        chunks = tuple(chunk for group in chunks_by_document for chunk in group)
        documents = tuple(
            self._document_record(document, len(chunks_by_document[index]))
            for index, document in enumerate(parsed)
        )
        validate_records(parsed, documents, chunks, self.config)
        return self._bundle(documents, chunks)

    async def build(self) -> ArtifactBundle:
        bundle = await self.expected_bundle()
        await asyncio.to_thread(write_transactionally, bundle, self.config.output_root)
        validate_artifacts(self.config.output_root)
        return bundle

    async def check(self) -> ArtifactBundle:
        expected = await self.expected_bundle()
        stale = [
            filename
            for filename, content in expected.files.items()
            if not (self.config.output_root / filename).is_file()
            or (self.config.output_root / filename).read_bytes() != content
        ]
        if stale:
            raise ArtifactDriftError(f"stale artifacts: {', '.join(sorted(stale))}")
        return expected

    async def validate(self) -> ArtifactBundle:
        report = validate_artifacts(self.config.output_root)
        expected = await self.expected_bundle()
        if (
            report.document_count != expected.manifest.document_count
            or report.chunk_count != expected.manifest.chunk_count
        ):
            raise ArtifactValidationError("artifact counts differ from current sources")
        actual_manifest = IngestionManifest.model_validate_json(
            (self.config.output_root / "ingestion_manifest.json").read_text(encoding="utf-8")
        )
        if actual_manifest.build_fingerprint != expected.manifest.build_fingerprint:
            raise ArtifactValidationError("artifact build fingerprint is not reproducible")
        return expected

    def _document_record(self, document: ParsedDocument, chunk_count: int) -> DocumentRecord:
        metadata = document.source.metadata
        return DocumentRecord(
            schema_version=DOCUMENT_SCHEMA_VERSION,
            document_id=metadata.document_id,
            title=metadata.title,
            source=metadata.source,
            source_file=document.source.source_file,
            department=metadata.department,
            document_type=metadata.document_type,
            access_level=metadata.access_level,
            allowed_roles=metadata.allowed_roles,
            created_date=metadata.created_date,
            updated_date=metadata.updated_date,
            version=metadata.version,
            owner=metadata.owner,
            status=metadata.status,
            tags=metadata.tags,
            related_document_ids=metadata.related_document_ids,
            original_content_hash=document.source.original_content_hash,
            normalized_content_hash=document.normalized_content_hash,
            approximate_word_count=len(re.findall(r"\b[\w-]+\b", document.normalized_body)),
            approximate_token_count=self.tokenizer.count(document.normalized_body),
            heading_paths=document.heading_paths,
            chunk_count=chunk_count,
        )

    def _bundle(
        self,
        documents: tuple[DocumentRecord, ...],
        chunks: tuple[ChunkRecord, ...],
    ) -> ArtifactBundle:
        document_bytes = jsonl(documents)
        chunk_bytes = jsonl(chunks)
        descriptors = (
            ArtifactDescriptor(
                filename="documents.jsonl",
                sha256=hashlib.sha256(document_bytes).hexdigest(),
            ),
            ArtifactDescriptor(
                filename="chunks.jsonl",
                sha256=hashlib.sha256(chunk_bytes).hexdigest(),
            ),
        )
        source_manifest_bytes = (
            self.config.source_root / "data/sample_documents/manifest.json"
        ).read_bytes()
        source_manifest_hash = hashlib.sha256(source_manifest_bytes).hexdigest()
        chunking = ChunkingConfig(
            target_chunk_tokens=self.config.target_chunk_tokens,
            maximum_chunk_tokens=self.config.maximum_chunk_tokens,
            overlap_tokens=self.config.overlap_tokens,
            minimum_chunk_tokens=self.config.minimum_chunk_tokens,
        )
        fingerprint_payload = {
            "pipeline_version": PIPELINE_VERSION,
            "document_schema_version": DOCUMENT_SCHEMA_VERSION,
            "chunk_schema_version": CHUNK_SCHEMA_VERSION,
            "source_manifest_sha256": source_manifest_hash,
            "chunking": chunking.model_dump(mode="json"),
            "tokenizer": {"name": self.tokenizer.name, "version": self.tokenizer.version},
            "source_document_hashes": [document.original_content_hash for document in documents],
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        manifest = IngestionManifest(
            ingestion_pipeline_version=PIPELINE_VERSION,
            document_schema_version=DOCUMENT_SCHEMA_VERSION,
            chunk_schema_version=CHUNK_SCHEMA_VERSION,
            source_manifest_sha256=source_manifest_hash,
            chunking_configuration=chunking,
            tokenizer_name=self.tokenizer.name,
            tokenizer_version=self.tokenizer.version,
            document_count=len(documents),
            chunk_count=len(chunks),
            evidence_count=len({chunk.evidence_id for chunk in chunks}),
            count_by_document_type=dict(
                sorted(Counter(item.document_type.value for item in documents).items())
            ),
            count_by_department=dict(
                sorted(Counter(item.department for item in documents).items())
            ),
            count_by_access_level=dict(
                sorted(Counter(item.access_level.value for item in documents).items())
            ),
            artifacts=descriptors,
            build_fingerprint=fingerprint,
        )
        manifest_bytes = (canonical_json(manifest) + "\n").encode("utf-8")
        return ArtifactBundle(
            files={
                "documents.jsonl": document_bytes,
                "chunks.jsonl": chunk_bytes,
                "ingestion_manifest.json": manifest_bytes,
            },
            documents=documents,
            chunks=chunks,
            manifest=manifest,
        )
