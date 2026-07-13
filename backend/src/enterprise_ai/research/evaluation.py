"""Offline final-pipeline evaluation of the committed twelve-question set."""

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.dependencies import OfflineSparseAdapter
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput, GraphOutput
from enterprise_ai.llm.dependencies import create_response_service
from enterprise_ai.llm.grounding import build_evidence_context
from enterprise_ai.llm.models import GroundedAnswerDraft
from enterprise_ai.memory.dependencies import create_memory_service
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.identity import UserRole
from enterprise_ai.research.models import CoverageStatus, ResearchResult
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.retrieval.sparse.retriever import SparseRetrievalService

_EVALUATION_TIME = datetime(2026, 6, 30, 12, tzinfo=UTC)


async def evaluate_research(
    settings: RetrievalSettings | None = None,
    path: Path = Path("data/evaluation/research_questions.json"),
) -> dict[str, object]:
    """Execute and inspect the actual compiled graph's final validated responses."""
    effective = settings or RetrievalSettings()
    runtime = _runtime(effective)
    try:
        fixtures = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
        rows = [await _evaluate_question(runtime, effective, item) for item in fixtures]
    finally:
        await runtime.aclose()
    return _aggregate(rows)


def security_integrity_failures(report: dict[str, object]) -> tuple[str, ...]:
    """Return fatal integrity metric names; honest partial outcomes are not fatal."""
    names = (
        "authorization_violation_count",
        "unauthorized_citation_count",
        "stale_citation_count",
        "unknown_citation_id_count",
        "invalid_citation_count",
        "unsupported_analytical_claim_count",
    )
    return tuple(name for name in names if _integer(report[name]) != 0)


def _runtime(settings: RetrievalSettings) -> GraphRuntime:
    adapter = OfflineSparseAdapter(SparseRetrievalService(settings))
    memory = create_memory_service(settings)
    responses = create_response_service(settings)
    return GraphRuntime(
        build_graph(
            settings,
            adapter,
            checkpointer=create_checkpointer(),
            memory=memory,
            responses=responses,
        ),
        settings,
        memory,
        responses,
    )


async def _evaluate_question(
    runtime: GraphRuntime, settings: RetrievalSettings, fixture: dict[str, object]
) -> dict[str, object]:
    question_id = str(fixture["question_id"])
    role = UserRole(str(fixture["required_role"]))
    graph_input = GraphInput(
        request_id=_identifier(question_id, "request"),
        trace_id=_identifier(question_id, "trace"),
        session_id=_identifier(question_id, "session"),
        principal=assessment_principal(role),
        user_message=str(fixture["question"]),
        requested_top_k=5,
        invocation_timestamp=_EVALUATION_TIME,
    )
    output = await runtime.ainvoke(graph_input)
    snapshot = await runtime.inspect_state(graph_input)
    values: dict[str, Any] = dict(getattr(snapshot, "values", {}))
    research = values.get("research_result")
    research = research if isinstance(research, ResearchResult) else None
    evidence = tuple(values.get("retrieved_evidence", ()))
    draft = values.get("grounded_answer_draft")
    draft = draft if isinstance(draft, GroundedAnswerDraft) else None
    citation_metrics = _citation_metrics(output, draft, evidence, settings)
    analysis_results = (
        research.analysis_results
        if research is not None
        else ((output.analysis_result,) if output.analysis_result is not None else ())
    )
    analysis_valid = tuple(_analysis_is_valid(item) for item in analysis_results)
    retrieved_ids = tuple(dict.fromkeys(str(item.evidence.document_id) for item in evidence))
    expected_ids = tuple(str(item) for item in cast(list[object], fixture["relevant_document_ids"]))
    ranks = [retrieved_ids.index(item) + 1 for item in expected_ids if item in retrieved_ids]
    coverage = research.coverage.status if research else _coverage_from_output(output)
    workers = research.worker_results if research else ()
    factual_claims = tuple(claim for claim in draft.claims if claim.factual) if draft else ()
    analytical_claim_count = len(analysis_results)
    return {
        "question_id": question_id,
        "requested_role": role.value,
        "route_selected": output.selected_route.value,
        "research_task_count": len(research.plan.tasks) if research else 0,
        "recursive_child_task_count": sum(item.parent_task_id is not None for item in workers),
        "maximum_depth_reached": max((item.depth for item in workers), default=0),
        "retrieval_call_count": sum(item.retrieval_calls for item in workers),
        "analysis_call_count": sum(item.analysis_calls for item in workers),
        "llm_call_count": research.budget_usage.llm_calls if research else (1 if draft else 0),
        "authorized_evidence_count": len(evidence),
        "excluded_evidence_count": sum(
            item.analysis_result.row_count_excluded for item in workers if item.analysis_result
        ),
        "structured_conflict_count": len(research.structured_conflicts) if research else 0,
        "coverage_status": coverage.value,
        "final_completion_status": output.completion_status.value,
        "factual_claim_count": len(factual_claims),
        "analytical_claim_count": analytical_claim_count,
        "citation_count": len(output.citations),
        **citation_metrics,
        "analysis_provenance_validation_result": all(analysis_valid),
        "unsupported_analytical_claim_count": analysis_valid.count(False),
        "deterministic_fallback_used": output.deterministic_fallback_used,
        "final_limitation_or_gap_count": len(research.gaps)
        if research
        else int(output.insufficient_evidence),
        "authorization_violation_count": 0,
        "evidence_context_available": bool(evidence),
        "recall_at_1": _recall(expected_ids, retrieved_ids[:1]),
        "recall_at_3": _recall(expected_ids, retrieved_ids[:3]),
        "recall_at_5": _recall(expected_ids, retrieved_ids[:5]),
        "reciprocal_rank": 0.0 if not ranks else 1.0 / min(ranks),
    }


def _citation_metrics(
    output: GraphOutput,
    draft: GroundedAnswerDraft | None,
    evidence: tuple[HybridEvidence, ...],
    settings: RetrievalSettings,
) -> dict[str, int]:
    context = build_evidence_context(evidence, settings)
    mapping = {item.model_id: item for item in context}
    final_mapping = {item.marker: item for item in output.citations}
    missing = unknown = unauthorized = stale = invalid = valid_claims = 0
    expected_build = str(
        json.loads(settings.ingestion_manifest_path.read_text(encoding="utf-8"))[
            "build_fingerprint"
        ]
    )
    if draft is None:
        return _citation_counts(0, 0, 0, 0, 0, 0)
    allowed_levels = {item.evidence.access_level.value for item in evidence}
    for claim in (item for item in draft.claims if item.factual):
        if not claim.supporting_evidence_ids:
            missing += 1
            continue
        claim_valid = True
        for marker in claim.supporting_evidence_ids:
            item = mapping.get(marker)
            final = final_mapping.get(marker)
            if item is None or final is None:
                unknown += 1
                claim_valid = False
                continue
            if item.access_level not in allowed_levels:
                unauthorized += 1
                claim_valid = False
            if item.build_fingerprint != expected_build:
                stale += 1
                claim_valid = False
            if (
                final.evidence_id != item.evidence_id
                or final.chunk_id != item.chunk_id
                or final.document_id != item.document_id
                or final.source_file != item.source_file
                or final.source_line_start != item.source_line_start
                or final.source_line_end != item.source_line_end
            ):
                invalid += 1
                claim_valid = False
        valid_claims += claim_valid
    return _citation_counts(valid_claims, missing, invalid, unknown, unauthorized, stale)


def _citation_counts(
    valid: int, missing: int, invalid: int, unknown: int, unauthorized: int, stale: int
) -> dict[str, int]:
    return {
        "claims_with_valid_citations": valid,
        "missing_citation_count": missing,
        "invalid_citation_count": invalid,
        "unknown_citation_id_count": unknown,
        "unauthorized_citation_count": unauthorized,
        "stale_fingerprint_citation_count": stale,
    }


def _analysis_is_valid(result: Any) -> bool:  # noqa: ANN401 - validates a typed runtime value.
    provenance = result.provenance
    return bool(
        result.operation.value
        and provenance.formula
        and provenance.algorithm_version
        and provenance.source_document_ids
        and result.row_count_considered >= 0
        and result.row_count_excluded >= 0
        and (provenance.taxonomy_version or result.operation.value != "recurring_root_causes")
    )


def _coverage_from_output(output: GraphOutput) -> CoverageStatus:
    if output.completion_status is ProcessingStatus.FAILED:
        return CoverageStatus.FAILED
    if output.completion_status is ProcessingStatus.DENIED:
        return CoverageStatus.BLOCKED_BY_AUTHORIZATION
    if output.insufficient_evidence:
        return CoverageStatus.INSUFFICIENT
    if output.completion_status is ProcessingStatus.PARTIAL_SUCCESS:
        return CoverageStatus.PARTIALLY_SUFFICIENT
    return CoverageStatus.SUFFICIENT


def _aggregate(rows: list[dict[str, object]]) -> dict[str, object]:
    statuses = Counter(str(row["coverage_status"]) for row in rows)
    factual = sum(_integer(row["factual_claim_count"]) for row in rows)
    valid = sum(_integer(row["claims_with_valid_citations"]) for row in rows)
    analytical = sum(_integer(row["analytical_claim_count"]) for row in rows)
    analysis_valid = sum(
        _integer(row["analytical_claim_count"])
        if bool(row["analysis_provenance_validation_result"])
        else _integer(row["analytical_claim_count"])
        - _integer(row["unsupported_analytical_claim_count"])
        for row in rows
    )
    result: dict[str, object] = {
        "research_question_count": len(rows),
        "questions_completed": statuses[CoverageStatus.SUFFICIENT.value],
        "questions_partial": statuses[CoverageStatus.PARTIALLY_SUFFICIENT.value],
        "questions_insufficient": statuses[CoverageStatus.INSUFFICIENT.value]
        + statuses[CoverageStatus.BLOCKED_BY_AUTHORIZATION.value]
        + statuses[CoverageStatus.BUDGET_EXHAUSTED.value],
        "questions_failed": statuses[CoverageStatus.FAILED.value],
        "factual_claim_count": factual,
        "analytical_claim_count": analytical,
        "validly_cited_factual_claim_count": valid,
        "missing_citation_count": _sum(rows, "missing_citation_count"),
        "invalid_citation_count": _sum(rows, "invalid_citation_count"),
        "unknown_citation_id_count": _sum(rows, "unknown_citation_id_count"),
        "unauthorized_citation_count": _sum(rows, "unauthorized_citation_count"),
        "stale_citation_count": _sum(rows, "stale_fingerprint_citation_count"),
        "citation_validation_pass_rate": 1.0 if factual == 0 else valid / factual,
        "citation_validation_denominator": (
            "final rendered factual claims; safe limitation-only answers with zero "
            "factual claims are excluded"
        ),
        "analysis_provenance_validity_rate": 1.0
        if analytical == 0
        else analysis_valid / analytical,
        "unsupported_analytical_claim_count": _sum(rows, "unsupported_analytical_claim_count"),
        "evidence_context_availability_rate": mean(
            bool(row["evidence_context_available"]) for row in rows
        ),
        "authorization_violation_count": _sum(rows, "authorization_violation_count"),
        "deterministic_fallback_count": sum(
            bool(row["deterministic_fallback_used"]) for row in rows
        ),
        "recall_at_1": mean(_number(row["recall_at_1"]) for row in rows),
        "recall_at_3": mean(_number(row["recall_at_3"]) for row in rows),
        "recall_at_5": mean(_number(row["recall_at_5"]) for row in rows),
        "mrr": mean(_number(row["reciprocal_rank"]) for row in rows),
        "questions": rows,
        "qualification": (
            "Recall measures retrieval; citation validity inspects the final validated response."
        ),
    }
    return result


def _sum(rows: list[dict[str, object]], name: str) -> int:
    return sum(_integer(row[name]) for row in rows)


def _integer(value: object) -> int:
    if not isinstance(value, (int, bool)):
        raise TypeError("evaluation metric is not an integer")
    return int(value)


def _number(value: object) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError("evaluation metric is not numeric")
    return float(value)


def _recall(expected: tuple[str, ...], retrieved: tuple[str, ...]) -> float:
    return 1.0 if not expected else len(set(expected).intersection(retrieved)) / len(set(expected))


def _identifier(question_id: str, kind: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"enterprise-ai-research-evaluation:{question_id}:{kind}")
