"""Authorized asynchronous local BM25 retrieval service."""

import json
import math
from collections import Counter
from datetime import date
from typing import Annotated
from uuid import UUID

from enterprise_ai_ingestion.models import ChunkRecord
from pydantic import BaseModel, ConfigDict, Field

from enterprise_ai.models.identity import AccessLevel, AuthenticatedPrincipal, UserRole
from enterprise_ai.models.retrieval import DocumentMetadata, DocumentType
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.exceptions import RetrievalDataIntegrityError, RetrievalValidationError
from enterprise_ai.retrieval.filters import DenseQueryFilters, build_authorization_filter
from enterprise_ai.retrieval.identifiers import (
    extract_enterprise_identifiers,
    matching_document_ids,
)
from enterprise_ai.retrieval.indexer import load_current_chunks
from enterprise_ai.retrieval.sparse.analyzer import analyze
from enterprise_ai.retrieval.sparse.artifacts import validate_sparse
from enterprise_ai.retrieval.sparse.bm25 import score_corpus
from enterprise_ai.retrieval.sparse.relevance import (
    has_adequate_support,
    matched_salient_terms,
    salient_query_terms,
)
from enterprise_ai.security.authorization import AuthorizationService


class SparseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sparse_score: Annotated[float, Field(ge=0)]
    chunk_id: UUID
    evidence_id: UUID
    document_id: UUID
    title: str
    source: str
    source_file: str
    section: str
    section_path: tuple[str, ...]
    source_line_start: int
    source_line_end: int
    version: str
    updated_date: date
    access_level: AccessLevel
    allowed_roles: frozenset[UserRole]
    document_type: DocumentType
    department: str
    status: str
    text: str
    chunk_content_hash: str
    build_fingerprint: str
    sparse_build_fingerprint: str
    salient_query_terms: tuple[str, ...] = ()
    matched_query_terms: tuple[str, ...] = ()
    salient_term_coverage: Annotated[float, Field(ge=0, le=1)] = 0


class SparseRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence: tuple[SparseEvidence, ...]
    total_candidates: int
    dropped_unauthorized: int = 0
    malformed_results: int = 0


class SparseRetrievalService:
    def __init__(
        self, settings: RetrievalSettings, authorization: AuthorizationService | None = None
    ) -> None:
        self.settings = settings
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
    ) -> SparseRetrievalResult:
        del request_id, trace_id
        selected_top_k = top_k or self.settings.pinecone_query_top_k
        if not 1 <= selected_top_k <= 100 or not query.strip():
            raise RetrievalValidationError("sparse query or top-k is invalid")
        try:
            query_terms = analyze(query, maximum_tokens=self.settings.bm25_max_query_tokens)
        except ValueError as error:
            raise RetrievalValidationError("sparse query analysis failed") from error
        if not query_terms:
            raise RetrievalValidationError("sparse query produced no terms")
        sparse_manifest = validate_sparse(self.settings)
        ingestion_manifest, chunks = load_current_chunks(self.settings)
        build_authorization_filter(
            principal, ingestion_manifest.build_fingerprint, filters, self.authorization
        )
        if sparse_manifest["ingestion_build_fingerprint"] != ingestion_manifest.build_fingerprint:
            raise RetrievalDataIntegrityError("sparse index belongs to another ingestion build")
        index = json.loads(self.settings.bm25_index_path.read_text(encoding="utf-8"))
        chunk_by_id = {str(chunk.chunk_id): chunk for chunk in chunks}
        authorized = {
            chunk_id: chunk
            for chunk_id, chunk in chunk_by_id.items()
            if self._authorized(principal, chunk, filters)
        }
        identifiers = extract_enterprise_identifiers(query)
        if identifiers:
            exact_document_ids = matching_document_ids(tuple(authorized.values()), identifiers)
            authorized = {
                chunk_id: chunk
                for chunk_id, chunk in authorized.items()
                if chunk.document_id in exact_document_ids
            }
        documents = {
            chunk_id: (
                int(value["length"]),
                {str(term): int(count) for term, count in value["term_frequencies"].items()},
            )
            for chunk_id, value in index["documents"].items()
            if chunk_id in authorized
        }
        if not documents:
            return SparseRetrievalResult(evidence=(), total_candidates=0)
        authorized_frequencies: Counter[str] = Counter()
        for _, frequencies in documents.values():
            authorized_frequencies.update(frequencies.keys())
        scored = score_corpus(
            query_terms,
            documents,
            authorized_frequencies,
            float(str(sparse_manifest["average_document_length"])),
            k1=self.settings.bm25_k1,
            b=self.settings.bm25_b,
        )
        salient_terms = salient_query_terms(query_terms)
        supported = []
        for item in scored:
            frequencies = documents[item.chunk_id][1]
            matched_terms = matched_salient_terms(salient_terms, frequencies)
            if has_adequate_support(salient_terms, matched_terms):
                supported.append((item, matched_terms))
        prefer_current = bool({"approved", "current"} & set(query_terms))
        if prefer_current:
            supported.sort(
                key=lambda row: (
                    authorized[row[0].chunk_id].status in {"archived", "draft", "superseded"},
                    -row[0].score,
                    row[0].chunk_id,
                )
            )
        evidence = tuple(
            self._evidence(
                authorized[item.chunk_id],
                item.score,
                ingestion_manifest.build_fingerprint,
                str(sparse_manifest["sparse_build_fingerprint"]),
                salient_terms,
                matched_terms,
            )
            for item, matched_terms in supported[:selected_top_k]
        )
        return SparseRetrievalResult(evidence=evidence, total_candidates=len(documents))

    def _authorized(
        self,
        principal: AuthenticatedPrincipal,
        chunk: ChunkRecord,
        filters: DenseQueryFilters | None,
    ) -> bool:
        metadata = DocumentMetadata(
            document_id=chunk.document_id,
            title=chunk.title,
            source=chunk.source,
            department=chunk.department,
            document_type=chunk.document_type,
            access_level=chunk.access_level,
            allowed_roles=frozenset(chunk.allowed_roles),
            created_date=chunk.created_date,
            updated_date=chunk.updated_date,
            version=chunk.version,
            content_hash=chunk.chunk_content_hash,
        )
        if not self.authorization.is_document_authorized(principal, metadata):
            return False
        if not filters:
            return True
        if filters.access_levels and chunk.access_level not in filters.access_levels:
            return False
        if filters.departments and chunk.department not in filters.departments:
            return False
        if filters.document_types and chunk.document_type not in filters.document_types:
            return False
        if filters.statuses and chunk.status not in filters.statuses:
            return False
        if filters.document_ids and chunk.document_id not in filters.document_ids:
            return False
        if filters.tags and not set(filters.tags).intersection(chunk.tags):
            return False
        return not (
            (filters.created_from and chunk.created_date < filters.created_from)
            or (filters.created_to and chunk.created_date > filters.created_to)
            or (filters.updated_from and chunk.updated_date < filters.updated_from)
            or (filters.updated_to and chunk.updated_date > filters.updated_to)
        )

    @staticmethod
    def _evidence(
        chunk: ChunkRecord,
        score: float,
        fingerprint: str,
        sparse_fingerprint: str,
        salient_terms: tuple[str, ...],
        matched_terms: tuple[str, ...],
    ) -> SparseEvidence:
        if not math.isfinite(score):
            raise RetrievalDataIntegrityError("BM25 produced a non-finite score")
        return SparseEvidence(
            sparse_score=score,
            chunk_id=chunk.chunk_id,
            evidence_id=chunk.evidence_id,
            document_id=chunk.document_id,
            title=chunk.title,
            source=chunk.source,
            source_file=chunk.source_file,
            section=chunk.section,
            section_path=chunk.section_path,
            source_line_start=chunk.source_line_start,
            source_line_end=chunk.source_line_end,
            version=chunk.version,
            updated_date=chunk.updated_date,
            access_level=chunk.access_level,
            allowed_roles=frozenset(chunk.allowed_roles),
            document_type=chunk.document_type,
            department=chunk.department,
            status=chunk.status,
            text=chunk.text,
            chunk_content_hash=chunk.chunk_content_hash,
            build_fingerprint=fingerprint,
            sparse_build_fingerprint=sparse_fingerprint,
            salient_query_terms=salient_terms,
            matched_query_terms=matched_terms,
            salient_term_coverage=len(matched_terms) / len(salient_terms),
        )
