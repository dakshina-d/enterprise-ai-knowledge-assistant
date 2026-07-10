"""Validated deterministic dense indexing and index verification."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from enterprise_ai_ingestion.models import ChunkRecord, IngestionManifest
from enterprise_ai_ingestion.validation import validate_artifacts

from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.embeddings import EmbeddingProvider
from enterprise_ai.retrieval.exceptions import (
    RetrievalDataIntegrityError,
    RetrievalDependencyError,
    RetrievalTimeoutError,
)
from enterprise_ai.retrieval.metadata import REQUIRED_RESULT_FIELDS, chunk_metadata
from enterprise_ai.retrieval.pinecone_client import PineconeGateway
from enterprise_ai.retrieval.retry import with_retries


@dataclass(frozen=True, slots=True)
class IndexSummary:
    expected_count: int
    indexed_count: int
    dimension: int
    build_fingerprint: str


def load_current_chunks(
    settings: RetrievalSettings,
) -> tuple[IngestionManifest, tuple[ChunkRecord, ...]]:
    output_root = settings.ingestion_manifest_path.parent
    validate_artifacts(output_root)
    manifest = IngestionManifest.model_validate_json(
        settings.ingestion_manifest_path.read_text(encoding="utf-8")
    )
    chunks = tuple(
        ChunkRecord.model_validate_json(line)
        for line in settings.ingestion_chunks_path.read_text(encoding="utf-8").splitlines()
    )
    if len(chunks) != manifest.chunk_count or len({chunk.chunk_id for chunk in chunks}) != len(
        chunks
    ):
        raise RetrievalDataIntegrityError("ingestion chunks are incomplete or duplicated")
    if any(
        "security_fixtures" in chunk.source_file or chunk.source_file.endswith("GLOSSARY.md")
        for chunk in chunks
    ):
        raise RetrievalDataIntegrityError("excluded source entered ingestion artifacts")
    return manifest, chunks


class DenseIndexer:
    def __init__(
        self,
        settings: RetrievalSettings,
        embeddings: EmbeddingProvider,
        gateway: PineconeGateway,
    ) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self.gateway = gateway

    async def bootstrap(self) -> int:
        self.settings.require_enabled()
        dimension = await self.embeddings.dimension()
        description = await self.gateway.describe_index(self.settings.pinecone_index_name)
        if description is None:
            await self.gateway.create_index(
                name=self.settings.pinecone_index_name,
                dimension=dimension,
                metric=self.settings.pinecone_metric,
                cloud=self.settings.pinecone_cloud,
                region=self.settings.pinecone_region,
            )
        await self._wait_compatible(dimension)
        return dimension

    async def _wait_compatible(self, dimension: int) -> dict[str, Any]:
        deadline = (
            asyncio.get_running_loop().time() + self.settings.pinecone_index_ready_timeout_seconds
        )
        while True:
            description = await self.gateway.describe_index(self.settings.pinecone_index_name)
            if description is None:
                raise RetrievalDependencyError("configured Pinecone index does not exist")
            if int(description.get("dimension") or 0) != dimension:
                raise RetrievalDataIntegrityError("Pinecone index dimension is incompatible")
            if str(description.get("metric")) != self.settings.pinecone_metric:
                raise RetrievalDataIntegrityError("Pinecone index metric is incompatible")
            status = description.get("status") or {}
            ready = status.get("ready") if isinstance(status, dict) else False
            if ready:
                return description
            if asyncio.get_running_loop().time() >= deadline:
                raise RetrievalDependencyError("Pinecone index readiness timed out")
            await asyncio.sleep(1)

    async def index(self) -> IndexSummary:
        manifest, chunks = load_current_chunks(self.settings)
        dimension = await self.bootstrap()
        records: list[dict[str, Any]] = []
        for start in range(0, len(chunks), self.settings.pinecone_embed_batch_size):
            batch = chunks[start : start + self.settings.pinecone_embed_batch_size]
            try:
                async with asyncio.timeout(self.settings.pinecone_request_timeout_seconds):
                    vectors = await self.embeddings.embed_documents(
                        [chunk.search_text for chunk in batch]
                    )
            except TimeoutError as error:
                raise RetrievalTimeoutError("embedding batch timed out") from error
            if any(len(vector) != dimension for vector in vectors):
                raise RetrievalDataIntegrityError("document embedding dimension mismatch")
            records.extend(
                {
                    "id": str(chunk.chunk_id),
                    "values": list(vector),
                    "metadata": chunk_metadata(
                        chunk,
                        build_fingerprint=manifest.build_fingerprint,
                        maximum_bytes=self.settings.pinecone_max_metadata_bytes,
                    ),
                }
                for chunk, vector in zip(batch, vectors, strict=True)
            )
        indexed = 0
        for start in range(0, len(records), self.settings.pinecone_upsert_batch_size):
            upsert_batch = records[start : start + self.settings.pinecone_upsert_batch_size]

            async def upsert_current_batch(
                batch: tuple[dict[str, Any], ...] = tuple(upsert_batch),
            ) -> int:
                return await self.gateway.upsert(batch, namespace=self.settings.pinecone_namespace)

            try:
                async with asyncio.timeout(self.settings.pinecone_request_timeout_seconds):
                    count = await with_retries(
                        upsert_current_batch,
                        maximum_retries=self.settings.pinecone_max_retries,
                        base_seconds=self.settings.pinecone_retry_base_seconds,
                    )
            except TimeoutError as error:
                raise RetrievalTimeoutError("upsert batch timed out") from error
            if count != len(upsert_batch):
                raise RetrievalDataIntegrityError("Pinecone reported a partial upsert")
            indexed += count
        await self.verify(manifest, chunks, dimension)
        return IndexSummary(len(chunks), indexed, dimension, manifest.build_fingerprint)

    async def verify(
        self,
        manifest: IngestionManifest | None = None,
        chunks: Sequence[ChunkRecord] | None = None,
        dimension: int | None = None,
    ) -> IndexSummary:
        if manifest is None or chunks is None:
            manifest, loaded = load_current_chunks(self.settings)
            chunks = loaded
        dimension = dimension or await self.embeddings.dimension()
        await self._wait_compatible(dimension)
        if await self.gateway.namespace_count(self.settings.pinecone_namespace) < len(chunks):
            raise RetrievalDataIntegrityError("namespace has fewer vectors than the current build")
        found = 0
        for start in range(0, len(chunks), 100):
            ids = [str(chunk.chunk_id) for chunk in chunks[start : start + 100]]
            fetched = await self.gateway.fetch(ids, namespace=self.settings.pinecone_namespace)
            if set(fetched) != set(ids):
                raise RetrievalDataIntegrityError("current Pinecone namespace is missing chunk IDs")
            for record in fetched.values():
                metadata = (
                    record.get("metadata")
                    if isinstance(record, dict)
                    else getattr(record, "metadata", None)
                )
                if not isinstance(metadata, dict) or not REQUIRED_RESULT_FIELDS <= metadata.keys():
                    raise RetrievalDataIntegrityError("indexed record attribution is incomplete")
                if metadata.get("build_fingerprint") != manifest.build_fingerprint:
                    raise RetrievalDataIntegrityError("indexed record build fingerprint is stale")
                found += 1
        return IndexSummary(len(chunks), found, dimension, manifest.build_fingerprint)

    async def close(self) -> None:
        await self.embeddings.close()
