"""Secure asynchronous dense retrieval with provider-output revalidation."""

import asyncio
import logging
import math
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from enterprise_ai_ingestion.models import IngestionManifest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from enterprise_ai.models.identity import AccessLevel, AuthenticatedPrincipal, UserRole
from enterprise_ai.models.retrieval import DocumentMetadata, DocumentType
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.embeddings import EmbeddingProvider
from enterprise_ai.retrieval.exceptions import (
    RetrievalDataIntegrityError,
    RetrievalTimeoutError,
    RetrievalValidationError,
)
from enterprise_ai.retrieval.filters import DenseQueryFilters, build_authorization_filter
from enterprise_ai.retrieval.metadata import REQUIRED_RESULT_FIELDS
from enterprise_ai.retrieval.pinecone_client import PineconeGateway
from enterprise_ai.retrieval.retry import with_retries
from enterprise_ai.security.authorization import AuthorizationService

logger = logging.getLogger(__name__)


class DenseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    record_id: str
    dense_score: float
    chunk_id: UUID
    evidence_id: UUID
    document_id: UUID
    title: str
    source: str
    source_file: str
    section: str
    section_path: tuple[str, ...]
    source_line_start: Annotated[int, Field(ge=1)]
    source_line_end: Annotated[int, Field(ge=1)]
    version: str
    updated_date: date
    access_level: AccessLevel
    allowed_roles: frozenset[UserRole]
    document_type: DocumentType
    department: str
    status: str
    text: str
    chunk_content_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    build_fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    @field_validator("dense_score")
    @classmethod
    def finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("dense score must be finite")
        return value


class DenseRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence: tuple[DenseEvidence, ...]
    total_provider_matches: int
    dropped_unauthorized: int
    malformed_results: int


class DenseRetrievalService:
    def __init__(
        self,
        settings: RetrievalSettings,
        embeddings: EmbeddingProvider,
        gateway: PineconeGateway,
        authorization: AuthorizationService | None = None,
    ) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self.gateway = gateway
        self.authorization = authorization or AuthorizationService()

    async def retrieve(
        self,
        principal: AuthenticatedPrincipal,
        query: str,
        *,
        top_k: int | None = None,
        filters: DenseQueryFilters | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> DenseRetrievalResult:
        normalized = " ".join(query.split())
        if not normalized or len(normalized) > 4_000:
            raise RetrievalValidationError("retrieval query is empty or too long")
        selected_top_k = top_k or self.settings.pinecone_query_top_k
        if not 1 <= selected_top_k <= 100:
            raise RetrievalValidationError("retrieval top-k is outside allowed bounds")
        manifest = IngestionManifest.model_validate_json(
            self.settings.ingestion_manifest_path.read_text(encoding="utf-8")
        )
        try:
            async with asyncio.timeout(self.settings.pinecone_request_timeout_seconds):
                vector = await self.embeddings.embed_query(normalized)
        except TimeoutError as error:
            raise RetrievalTimeoutError("query embedding timed out") from error
        dimension = await self.embeddings.dimension()
        if len(vector) != dimension:
            raise RetrievalDataIntegrityError("query embedding dimension mismatch")
        mandatory_filter = build_authorization_filter(
            principal, manifest.build_fingerprint, filters, self.authorization
        )
        logger.info(
            "dense query started",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "namespace": self.settings.pinecone_namespace,
                "top_k": selected_top_k,
            },
        )
        try:
            async with asyncio.timeout(self.settings.pinecone_request_timeout_seconds):
                matches = await with_retries(
                    lambda: self.gateway.query(
                        vector=vector,
                        top_k=selected_top_k,
                        namespace=self.settings.pinecone_namespace,
                        metadata_filter=mandatory_filter,
                        include_metadata=True,
                        include_values=False,
                    ),
                    maximum_retries=self.settings.pinecone_max_retries,
                    base_seconds=self.settings.pinecone_retry_base_seconds,
                )
        except TimeoutError as error:
            raise RetrievalTimeoutError("dense query timed out") from error
        evidence: list[DenseEvidence] = []
        dropped = 0
        malformed = 0
        for match in matches:
            try:
                item = _parse_match(
                    match, manifest.build_fingerprint, self.settings.pinecone_metric
                )
                metadata = DocumentMetadata(
                    document_id=item.document_id,
                    title=item.title,
                    source=item.source,
                    department=item.department,
                    document_type=item.document_type,
                    access_level=item.access_level,
                    allowed_roles=item.allowed_roles,
                    created_date=_metadata_value(match, "created_date"),
                    updated_date=item.updated_date,
                    version=item.version,
                    content_hash=item.chunk_content_hash,
                )
            except (ValidationError, ValueError, TypeError, RetrievalDataIntegrityError):
                malformed += 1
                continue
            if not self.authorization.is_document_authorized(principal, metadata):
                dropped += 1
                logger.warning(
                    "unauthorized provider result dropped",
                    extra={"request_id": request_id, "trace_id": trace_id},
                )
                continue
            evidence.append(item)
        return DenseRetrievalResult(
            evidence=tuple(evidence),
            total_provider_matches=len(matches),
            dropped_unauthorized=dropped,
            malformed_results=malformed,
        )

    async def close(self) -> None:
        await self.embeddings.close()


def _parse_match(match: Any, fingerprint: str, metric: str) -> DenseEvidence:
    metadata = _value(match, "metadata")
    if not isinstance(metadata, dict) or not REQUIRED_RESULT_FIELDS <= metadata.keys():
        raise RetrievalDataIntegrityError("provider result attribution is incomplete")
    if metadata.get("build_fingerprint") != fingerprint:
        raise RetrievalDataIntegrityError("provider result belongs to another ingestion build")
    score = float(_value(match, "score"))
    if not math.isfinite(score) or (metric == "cosine" and not -1.0 <= score <= 1.0):
        raise RetrievalDataIntegrityError("provider score is incompatible with configured metric")
    return DenseEvidence(
        record_id=str(_value(match, "id")),
        dense_score=score,
        **{
            field: metadata[field]
            for field in DenseEvidence.model_fields
            if field not in {"record_id", "dense_score"}
        },
    )


def _metadata_value(match: Any, name: str) -> Any:
    metadata = _value(match, "metadata")
    return metadata.get(name) if isinstance(metadata, dict) else None


def _value(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)
