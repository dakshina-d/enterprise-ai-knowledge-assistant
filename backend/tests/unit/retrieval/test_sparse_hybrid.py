"""Offline analyzer, BM25, sparse artifact, authorization, and fusion tests."""

import asyncio
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.models.retrieval import DocumentType
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.dense_retriever import DenseEvidence
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.hybrid.fusion import fuse
from enterprise_ai.retrieval.hybrid.normalization import normalize_scores
from enterprise_ai.retrieval.sparse.analyzer import analyze
from enterprise_ai.retrieval.sparse.artifacts import build_sparse, check_sparse, validate_sparse
from enterprise_ai.retrieval.sparse.bm25 import score_corpus
from enterprise_ai.retrieval.sparse.retriever import SparseEvidence, SparseRetrievalService
from enterprise_ai_ingestion.config import default_config
from enterprise_ai_ingestion.pipeline import IngestionPipeline


def _settings(tmp_path: Path) -> RetrievalSettings:
    bundle = asyncio.run(IngestionPipeline(default_config()).expected_bundle())
    output = tmp_path / "processed"
    output.mkdir()
    for name, content in bundle.files.items():
        (output / name).write_bytes(content)
    return RetrievalSettings(
        _env_file=None,
        ingestion_manifest_path=output / "ingestion_manifest.json",
        ingestion_chunks_path=output / "chunks.jsonl",
        bm25_index_path=output / "bm25_index.json",
        bm25_manifest_path=output / "bm25_manifest.json",
    )


def test_analyzer_preserves_identifiers_components_unicode_and_negation() -> None:
    tokens = analyze("INC-PAY-2026-004 HorizonPay JDBC payment_queue HTTP-504 TLS no")
    assert "inc-pay-2026-004" in tokens
    assert {"inc", "pay", "2026", "004"} <= set(tokens)
    assert {
        "horizonpay",
        "jdbc",
        "payment_queue",
        "payment",
        "queue",
        "http-504",
        "tls",
        "no",
    } <= set(tokens)
    assert tokens == analyze("INC-PAY-2026-004 HorizonPay JDBC payment_queue HTTP-504 TLS no")


def test_bm25_exact_rare_term_ranks_first_and_is_deterministic() -> None:
    documents = {
        "a": (4, {"common": 2, "inc-pay-2026-004": 1}),
        "b": (3, {"common": 2}),
    }
    result = score_corpus(
        ("inc-pay-2026-004",),
        documents,
        {"common": 2, "inc-pay-2026-004": 1},
        3.5,
        k1=1.5,
        b=0.75,
    )
    assert result[0].chunk_id == "a" and result[0].score > 0
    assert result == score_corpus(
        ("inc-pay-2026-004",), documents, {"common": 2, "inc-pay-2026-004": 1}, 3.5, k1=1.5, b=0.75
    )
    with pytest.raises(ValueError):
        score_corpus((), documents, {}, 3.5, k1=1.5, b=0.75)


def test_sparse_artifacts_are_complete_deterministic_and_valid(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = build_sparse(settings)
    first_bytes = (settings.bm25_index_path.read_bytes(), settings.bm25_manifest_path.read_bytes())
    second = build_sparse(settings)
    assert first == second
    assert first["indexed_chunk_count"] == 83
    assert first_bytes == (
        settings.bm25_index_path.read_bytes(),
        settings.bm25_manifest_path.read_bytes(),
    )
    assert check_sparse(settings) == validate_sparse(settings)


def test_sparse_retrieval_exact_identifier_and_rbac(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    build_sparse(settings)
    service = SparseRetrievalService(settings)
    analyst = asyncio.run(
        service.retrieve(assessment_principal(UserRole.ANALYST), "INC-PAY-2026-031", top_k=5)
    )
    viewer = asyncio.run(
        service.retrieve(assessment_principal(UserRole.VIEWER), "INC-PAY-2026-031", top_k=5)
    )
    assert analyst.evidence
    assert all(item.access_level is not AccessLevel.RESTRICTED for item in analyst.evidence)
    assert all(
        item.access_level in {AccessLevel.PUBLIC, AccessLevel.INTERNAL} for item in viewer.evidence
    )


def _dense(identifier: str, score: float) -> DenseEvidence:
    chunk_id = UUID(identifier)
    return DenseEvidence(
        record_id=identifier,
        dense_score=score,
        chunk_id=chunk_id,
        evidence_id=chunk_id,
        document_id=chunk_id,
        title="Title",
        source="source",
        source_file="safe.md",
        section="Section",
        section_path=("Section",),
        source_line_start=1,
        source_line_end=2,
        version="1",
        updated_date=date(2026, 1, 1),
        access_level=AccessLevel.INTERNAL,
        allowed_roles=frozenset({UserRole.VIEWER}),
        document_type=DocumentType.RUNBOOK,
        department="payments",
        status="active",
        text="Evidence",
        chunk_content_hash="a" * 64,
        build_fingerprint="b" * 64,
    )


def _sparse(dense: DenseEvidence, score: float) -> SparseEvidence:
    values = dense.model_dump()
    values.pop("record_id")
    values.pop("dense_score")
    return SparseEvidence(
        **values,
        sparse_score=score,
        sparse_build_fingerprint="c" * 64,
    )


def test_normalization_and_hybrid_fusion_preserve_raw_scores_and_order() -> None:
    first = _dense("00000000-0000-0000-0000-000000000001", -0.5)
    second = _dense("00000000-0000-0000-0000-000000000002", 0.5)
    sparse = _sparse(first, 4.0)
    assert normalize_scores({"a": -0.5, "b": 0.5}) == {"a": 0.0, "b": 1.0}
    assert normalize_scores({"a": 3.0}) == {"a": 1.0}
    result = fuse((first, second), (sparse,), dense_weight=0.65, sparse_weight=0.35, top_k=5)
    assert len(result) == 2
    assert len({item.evidence.chunk_id for item in result}) == 2
    assert all(0 <= item.hybrid_score <= 1 for item in result)
    assert any(item.raw_dense_score == -0.5 and item.raw_sparse_score == 4.0 for item in result)
