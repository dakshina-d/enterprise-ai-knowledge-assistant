import pytest
from enterprise_ai.research.coverage import assess_coverage
from enterprise_ai.research.models import CoverageStatus

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
