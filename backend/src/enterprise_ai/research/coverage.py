"""Deterministic coverage and gap assessment."""

import calendar
import math
import re
from collections import Counter

from enterprise_ai.research.models import (
    CoverageStatus,
    ResearchConflict,
    ResearchCoverageAssessment,
    ResearchPlan,
    ResearchTaskStatus,
    ResearchWorkerResult,
)
from enterprise_ai.retrieval.hybrid.models import HybridEvidence

_MONTHS = {
    name.casefold(): number for number, name in enumerate(calendar.month_name) if number and name
}
_YEARS = re.compile(r"^(?:19|20)\d{2}$")


def evidence_supports_task(item: HybridEvidence, task: object) -> bool:
    terms = tuple(getattr(task, "comparison_terms", ()))
    if not terms:
        return True
    source = item.evidence
    haystack = " ".join(
        (
            source.title,
            source.section,
            source.text,
            source.updated_date.strftime("%B %Y"),
        )
    ).casefold()
    temporal = tuple(term for term in terms if term in _MONTHS or _YEARS.fullmatch(term))
    subject = tuple(term for term in terms if term not in temporal)
    if any(term not in haystack for term in temporal):
        return False
    required_subject_matches = max(1, math.ceil(len(subject) / 2)) if subject else 0
    return sum(term in haystack for term in subject) >= required_subject_matches


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
    comparison_tasks = {
        task.comparison_dimension: task
        for task in plan.tasks
        if task.comparison_dimension is not None
    }
    if plan.required_comparison_dimensions:
        covered = []
        for dimension in plan.required_comparison_dimensions:
            task = comparison_tasks.get(dimension)
            if task is None:
                continue
            if any(
                result.comparison_dimension == dimension
                and any(evidence_supports_task(item, task) for item in result.evidence)
                for result in results
            ):
                covered.append(dimension)
        covered_dimensions = tuple(covered)
        missing = tuple(
            dimension
            for dimension in plan.required_comparison_dimensions
            if dimension not in covered_dimensions
        )
    else:
        covered_dimensions = tuple(
            task.research_question for task in plan.tasks if task.task_id in completed
        )
        missing = tuple(
            task.research_question for task in plan.tasks if task.task_id not in completed
        )
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
        covered_dimensions=covered_dimensions,
        missing_dimensions=missing,
        evidence_diversity=len(
            {item.evidence.document_id for result in results for item in result.evidence}
        ),
        source_authority_distribution=tuple(sorted(authority.items())),
        conflicts=conflicts,
        another_round_justified=bool(missing and not budget_exhausted),
    )
