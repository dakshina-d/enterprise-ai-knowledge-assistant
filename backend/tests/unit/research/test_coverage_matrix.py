from datetime import date

import pytest
from enterprise_ai.research.coverage import assess_coverage
from enterprise_ai.research.models import (
    CollectionCatalog,
    CoverageStatus,
    ResearchPlan,
    ResearchSearchStrategy,
    ResearchTask,
    ResearchTaskType,
)

from .evidence_fixtures import evidence, result
from .test_compiled_rounds import _plan


@pytest.mark.parametrize(
    ("evidence_count", "budget", "blocked", "failed", "expected"),
    (
        (1, False, False, False, CoverageStatus.SUFFICIENT),
        (0, False, False, False, CoverageStatus.INSUFFICIENT),
        (1, True, False, False, CoverageStatus.BUDGET_EXHAUSTED),
        (1, False, True, False, CoverageStatus.BLOCKED_BY_AUTHORIZATION),
        (1, False, False, True, CoverageStatus.FAILED),
    ),
)
def test_deterministic_coverage_precedence(
    evidence_count: int,
    budget: bool,
    blocked: bool,
    failed: bool,
    expected: CoverageStatus,
) -> None:
    assessment = assess_coverage(
        _plan(),
        (result("T01", (evidence(1),)),),
        evidence_count,
        (),
        budget_exhausted=budget,
        authorization_blocked=blocked,
        failed=failed,
    )
    assert assessment.status is expected


def test_missing_mandatory_task_is_partial_with_evidence() -> None:
    assessment = assess_coverage(
        _plan(2), (result("T01", (evidence(1),)),), 1, (), budget_exhausted=False
    )
    assert assessment.status is CoverageStatus.PARTIALLY_SUFFICIENT
    assert assessment.missing_dimensions == ("Initial dimension 2",)


def _comparison_plan() -> ResearchPlan:
    dimensions = ("primary latency in March", "secondary availability in April")
    return ResearchPlan(
        plan_id="RP-comparison",
        original_question="compare",
        normalized_objective="compare",
        research_scope="authorized",
        authorized_collection_summary=CollectionCatalog(
            build_fingerprint="b" * 64,
            document_count=2,
            departments=(),
            document_types=("incident",),
            statuses=("final",),
        ),
        tasks=tuple(
            ResearchTask(
                task_id=f"T0{index}",
                depth=0,
                task_type=ResearchTaskType.COMPARISON_DIMENSION,
                research_question=dimension,
                search=ResearchSearchStrategy(queries=(dimension,)),
                comparison_dimension=dimension,
                comparison_terms=tuple(
                    word.casefold() for word in dimension.split() if word.casefold() != "in"
                ),
            )
            for index, dimension in enumerate(dimensions, 1)
        ),
        required_comparison_dimensions=dimensions,
    )


def test_comparison_coverage_requires_each_dimension_and_specific_evidence() -> None:
    plan = _comparison_plan()
    march = evidence(
        1,
        document_id=evidence(1).evidence.document_id,
        title="Primary latency",
        text="Primary latency affected requests.",
        updated_date=date(2026, 3, 2),
    )
    april = evidence(
        2,
        document_id=evidence(2).evidence.document_id,
        title="Secondary availability",
        text="Secondary availability was reduced.",
        updated_date=date(2026, 4, 2),
    )
    first = result("T01", (march,)).model_copy(
        update={"comparison_dimension": plan.required_comparison_dimensions[0]}
    )
    partial = assess_coverage(plan, (first,), 1, (), budget_exhausted=False)
    assert partial.status is CoverageStatus.PARTIALLY_SUFFICIENT
    assert partial.missing_dimensions == (plan.required_comparison_dimensions[1],)

    second = result("T02", (april,)).model_copy(
        update={"comparison_dimension": plan.required_comparison_dimensions[1]}
    )
    sufficient = assess_coverage(plan, (first, second), 2, (), budget_exhausted=False)
    assert sufficient.status is CoverageStatus.SUFFICIENT
    assert sufficient.missing_dimensions == ()


def test_duplicate_document_does_not_cover_unmatched_dimension_but_may_cover_both() -> None:
    plan = _comparison_plan().model_copy(
        update={
            "tasks": tuple(
                task.model_copy(
                    update={
                        "comparison_terms": (
                            ("primary", "latency") if index == 0 else ("secondary", "availability")
                        )
                    }
                )
                for index, task in enumerate(_comparison_plan().tasks)
            )
        }
    )
    one_sided = evidence(3, title="Primary latency", text="Primary latency only.")
    results = tuple(
        result(task.task_id, (one_sided,)).model_copy(
            update={"comparison_dimension": task.comparison_dimension}
        )
        for task in plan.tasks
    )
    partial = assess_coverage(plan, results, 1, (), budget_exhausted=False)
    assert partial.status is CoverageStatus.PARTIALLY_SUFFICIENT

    both = evidence(
        4,
        document_id=one_sided.evidence.document_id,
        title="Combined review",
        text="Primary latency and secondary availability were reviewed together.",
    )
    both_results = tuple(
        result(task.task_id, (both,)).model_copy(
            update={"comparison_dimension": task.comparison_dimension}
        )
        for task in plan.tasks
    )
    sufficient = assess_coverage(plan, both_results, 1, (), budget_exhausted=False)
    assert sufficient.status is CoverageStatus.SUFFICIENT
