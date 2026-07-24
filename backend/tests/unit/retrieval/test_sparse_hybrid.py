"""Offline analyzer, BM25, sparse artifact, authorization, and fusion tests."""

import asyncio
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.models.retrieval import DocumentType
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.dense_retriever import DenseEvidence, DenseRetrievalResult
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.exceptions import RetrievalDependencyError
from enterprise_ai.retrieval.hybrid.fusion import fuse
from enterprise_ai.retrieval.hybrid.models import CompletionStatus
from enterprise_ai.retrieval.hybrid.normalization import normalize_scores
from enterprise_ai.retrieval.hybrid.retriever import HybridRetrievalService
from enterprise_ai.retrieval.sparse.analyzer import analyze
from enterprise_ai.retrieval.sparse.artifacts import build_sparse, check_sparse, validate_sparse
from enterprise_ai.retrieval.sparse.bm25 import score_corpus
from enterprise_ai.retrieval.sparse.retriever import (
    SparseEvidence,
    SparseRetrievalResult,
    SparseRetrievalService,
)
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


def test_sparse_relevance_abstains_for_unsupported_and_generic_queries(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    build_sparse(settings)
    service = SparseRetrievalService(settings)
    viewer = assessment_principal(UserRole.VIEWER)

    password = asyncio.run(service.retrieve(viewer, "Summarize the password policy.", top_k=5))
    generic = asyncio.run(service.retrieve(viewer, "policy", top_k=5))
    out_of_vocabulary = asyncio.run(service.retrieve(viewer, "xylophonicquasar", top_k=5))

    assert password.evidence == generic.evidence == out_of_vocabulary.evidence == ()


def test_sparse_relevance_retains_verified_viewer_runbook(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    build_sparse(settings)
    result = asyncio.run(
        SparseRetrievalService(settings).retrieve(
            assessment_principal(UserRole.VIEWER),
            (
                "What does the active Payment Queue Backlog Recovery Runbook require "
                "for controlled backlog drain and idempotency verification?"
            ),
            top_k=5,
        )
    )

    assert result.evidence
    assert result.evidence[0].source_file.endswith("payment-queue-backlog-recovery.md")
    assert result.evidence[0].salient_term_coverage >= 0.5
    assert {"backlog", "drain", "idempotency"} <= set(result.evidence[0].matched_query_terms)


def test_relevance_preserves_identifier_authorization_and_current_preference(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    build_sparse(settings)
    service = SparseRetrievalService(settings)
    administrator = asyncio.run(
        service.retrieve(
            assessment_principal(UserRole.ADMINISTRATOR),
            "INC-PAY-2026-031",
            top_k=5,
        )
    )
    viewer = asyncio.run(
        service.retrieve(
            assessment_principal(UserRole.VIEWER),
            "INC-PAY-2026-031",
            top_k=5,
        )
    )
    current = asyncio.run(
        service.retrieve(
            assessment_principal(UserRole.VIEWER),
            "What is the current approved data retention policy?",
            top_k=10,
        )
    )

    assert administrator.evidence[0].source_file.endswith("inc-pay-2026-031.md")
    assert all(item.access_level is not AccessLevel.RESTRICTED for item in viewer.evidence)
    assert current.evidence
    assert current.evidence[0].status != "superseded"
    superseded_ranks = [
        index for index, item in enumerate(current.evidence) if item.status == "superseded"
    ]
    if superseded_ranks:
        assert superseded_ranks[0] > 0


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


class RetrievalBranch:
    def __init__(self, result: object) -> None:
        self.result = result

    async def retrieve(self, *_args: object, **_kwargs: object) -> object:
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.mark.asyncio
@pytest.mark.parametrize(("failed", "expected_mode"), [("dense", "sparse"), ("sparse", "dense")])
async def test_hybrid_returns_only_safe_partial_branch(
    failed: str,
    expected_mode: str,
) -> None:
    item = _dense("00000000-0000-0000-0000-000000000001", 0.8)
    dense: object = DenseRetrievalResult(
        evidence=(item,),
        total_provider_matches=1,
        dropped_unauthorized=0,
        malformed_results=0,
    )
    sparse: object = SparseRetrievalResult(evidence=(_sparse(item, 2.0),), total_candidates=1)
    if failed == "dense":
        dense = RuntimeError("raw dense provider detail")
    else:
        sparse = RuntimeError("raw sparse provider detail")
    service = HybridRetrievalService(
        RetrievalSettings(),
        RetrievalBranch(dense),  # type: ignore[arg-type]
        RetrievalBranch(sparse),  # type: ignore[arg-type]
    )

    result = await service.retrieve(
        assessment_principal(UserRole.VIEWER),
        "safe query",
    )

    assert result.completion_status is CompletionStatus.PARTIAL_SUCCESS
    assert result.failed_branches == (failed,)
    assert all(expected_mode in candidate.retrieval_modes for candidate in result.evidence)
    assert "provider detail" not in repr(result)


@pytest.mark.asyncio
async def test_hybrid_complete_failure_and_cancellation_are_not_hidden() -> None:
    service = HybridRetrievalService(
        RetrievalSettings(),
        RetrievalBranch(RuntimeError("raw dense detail")),  # type: ignore[arg-type]
        RetrievalBranch(RuntimeError("raw sparse detail")),  # type: ignore[arg-type]
    )
    with pytest.raises(RetrievalDependencyError, match="failed safely"):
        await service.retrieve(assessment_principal(UserRole.VIEWER), "safe query")

    cancelled = HybridRetrievalService(
        RetrievalSettings(),
        RetrievalBranch(asyncio.CancelledError()),  # type: ignore[arg-type]
        RetrievalBranch(RuntimeError("raw sparse detail")),  # type: ignore[arg-type]
    )
    with pytest.raises(asyncio.CancelledError):
        await cancelled.retrieve(assessment_principal(UserRole.VIEWER), "safe query")


@pytest.mark.asyncio
async def test_hybrid_keeps_authorized_dense_semantic_evidence_when_sparse_abstains() -> None:
    item = _dense("00000000-0000-0000-0000-000000000001", 0.9)
    service = HybridRetrievalService(
        RetrievalSettings(),
        RetrievalBranch(
            DenseRetrievalResult(
                evidence=(item,),
                total_provider_matches=1,
                dropped_unauthorized=0,
                malformed_results=0,
            )
        ),  # type: ignore[arg-type]
        RetrievalBranch(SparseRetrievalResult(evidence=(), total_candidates=1)),  # type: ignore[arg-type]
    )

    result = await service.retrieve(
        assessment_principal(UserRole.VIEWER),
        "known semantic paraphrase",
    )

    assert len(result.evidence) == 1
    assert result.evidence[0].retrieval_modes == frozenset({"dense"})
