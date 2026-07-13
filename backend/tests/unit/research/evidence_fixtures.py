from datetime import date
from uuid import UUID

from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.models.retrieval import DocumentType
from enterprise_ai.research.models import CoverageStatus, ResearchTaskStatus, ResearchWorkerResult
from enterprise_ai.retrieval.dense_retriever import DenseEvidence
from enterprise_ai.retrieval.hybrid.models import HybridEvidence


def evidence(identifier: int, **changes: object) -> HybridEvidence:
    value = UUID(int=identifier)
    dense = DenseEvidence(
        record_id=str(value),
        dense_score=0.2,
        chunk_id=value,
        evidence_id=value,
        document_id=UUID(int=100),
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
    ).model_copy(update=changes)
    return HybridEvidence(
        evidence=dense,
        raw_dense_score=0.2,
        hybrid_score=0.5,
        final_rank=2,
        retrieval_modes=frozenset({"dense"}),
    )


def result(task_id: str, items: tuple[HybridEvidence, ...]) -> ResearchWorkerResult:
    return ResearchWorkerResult(
        task_id=task_id,
        parent_task_id=None,
        depth=0,
        status=ResearchTaskStatus.COMPLETED,
        queries_executed=("q",),
        retrieval_modes=("dense",),
        evidence=items,
        coverage_status=CoverageStatus.SUFFICIENT,
    )
