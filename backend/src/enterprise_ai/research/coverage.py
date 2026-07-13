"""Deterministic coverage and gap assessment."""

from collections import Counter

from enterprise_ai.research.models import (
    CoverageStatus,
    ResearchConflict,
    ResearchCoverageAssessment,
    ResearchPlan,
    ResearchTaskStatus,
    ResearchWorkerResult,
)


def assess_coverage(
    plan: ResearchPlan,
    results: tuple[ResearchWorkerResult, ...],
    evidence_count: int,
    conflicts: tuple[ResearchConflict, ...],
    *,
    budget_exhausted: bool,
    authorization_blocked: bool = False,
    failed: bool = False,
) -> ResearchCoverageAssessment:
    completed = {
        result.task_id for result in results if result.status is ResearchTaskStatus.COMPLETED
    }
    missing = tuple(task.research_question for task in plan.tasks if task.task_id not in completed)
    if authorization_blocked:
        status = CoverageStatus.BLOCKED_BY_AUTHORIZATION
    elif budget_exhausted:
        status = CoverageStatus.BUDGET_EXHAUSTED
    elif failed:
        status = CoverageStatus.FAILED
    elif not evidence_count:
        status = CoverageStatus.INSUFFICIENT
    elif missing:
        status = CoverageStatus.PARTIALLY_SUFFICIENT
    else:
        status = CoverageStatus.SUFFICIENT
    authority = Counter(
        result.evidence[0].evidence.status if result.evidence else "none" for result in results
    )
    return ResearchCoverageAssessment(
        status=status,
        covered_dimensions=tuple(
            task.research_question for task in plan.tasks if task.task_id in completed
        ),
        missing_dimensions=missing,
        evidence_diversity=len(
            {item.evidence.document_id for result in results for item in result.evidence}
        ),
        source_authority_distribution=tuple(sorted(authority.items())),
        conflicts=conflicts,
        another_round_justified=bool(missing and not budget_exhausted),
    )
