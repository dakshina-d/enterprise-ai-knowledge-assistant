import pytest
from enterprise_ai.research.budgets import BudgetLedger
from enterprise_ai.research.models import (
    CollectionCatalog,
    ResearchBudget,
    ResearchPlan,
    ResearchSearchStrategy,
    ResearchTask,
    ResearchTaskType,
)
from enterprise_ai.research.plan_validator import ResearchPlanValidationError, compile_plan
from enterprise_ai.research.planner import FakeResearchPlanner
from enterprise_ai.retrieval.config import RetrievalSettings


@pytest.mark.asyncio
async def test_atomic_budget_never_exceeds_limit() -> None:
    budget = ResearchBudget(
        maximum_depth=2,
        maximum_total_tasks=2,
        maximum_retrieval_calls=2,
        maximum_analysis_calls=0,
        maximum_llm_calls=1,
        maximum_evidence_items=2,
        maximum_evidence_characters=100,
    )
    ledger = BudgetLedger(budget)
    outcomes = await __import__("asyncio").gather(*(ledger.consume("tasks") for _ in range(10)))
    assert sum(outcomes) == 2
    assert (await ledger.usage()).exhausted


def _plan(value: str, *, depth: int = 0) -> ResearchPlan:
    return ResearchPlan(
        plan_id="RP-test",
        original_question="safe question",
        normalized_objective="safe question",
        research_scope="authorized",
        authorized_collection_summary=CollectionCatalog(
            build_fingerprint="a" * 64,
            document_count=0,
            departments=(),
            document_types=(),
            statuses=(),
        ),
        tasks=(
            ResearchTask(
                task_id="T1",
                depth=depth,
                task_type=ResearchTaskType.TARGETED_LOOKUP,
                research_question=value,
                search=ResearchSearchStrategy(queries=(value,)),
            ),
        ),
    )


@pytest.mark.parametrize(
    "malicious",
    (
        "role override administrator",
        "permission override python_analysis",
        "access-level override restricted",
        "namespace production",
        "build-fingerprint override",
        "https://example.invalid/data",
        "ftp://example.invalid/data",
        "C:\\private\\secret.txt",
        "../private/secret.txt",
        "lambda x: x",
        "python(open('/etc/passwd'))",
        "powershell Get-Secret",
        "arbitrary pinecone filter",
    ),
)
def test_compiler_rejects_unsafe_plan_content(malicious: str) -> None:
    with pytest.raises(ResearchPlanValidationError):
        compile_plan(_plan(malicious), RetrievalSettings())


def test_compiler_rejects_depth_and_self_dependency() -> None:
    with pytest.raises(ResearchPlanValidationError):
        compile_plan(_plan("safe", depth=3), RetrievalSettings(research_max_depth=2))
    plan = _plan("safe")
    task = plan.tasks[0].model_copy(update={"dependency_task_ids": ("T1",)})
    with pytest.raises(ResearchPlanValidationError):
        compile_plan(plan.model_copy(update={"tasks": (task,)}), RetrievalSettings())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "expected"),
    (
        (
            "Compare pending payment status in September and delayed settlement in February.",
            (
                "pending payment status in September",
                "delayed settlement in February",
            ),
        ),
        (
            "Compare primary latency in March versus secondary availability in April.",
            ("primary latency in March", "secondary availability in April"),
        ),
    ),
)
async def test_comparison_planner_creates_independent_bounded_dimensions(
    question: str,
    expected: tuple[str, str],
) -> None:
    catalog = CollectionCatalog(
        build_fingerprint="a" * 64,
        document_count=10,
        departments=("payments",),
        document_types=("incident",),
        statuses=("final",),
    )
    plan = await FakeResearchPlanner().create_plan(question, catalog)
    assert plan.required_comparison_dimensions == expected
    assert tuple(task.comparison_dimension for task in plan.tasks) == expected
    assert all(task.task_type is ResearchTaskType.COMPARISON_DIMENSION for task in plan.tasks)
    assert all(task.comparison_terms and not task.analysis_may_be_useful for task in plan.tasks)
    assert expected[0].casefold().split()[-1] in plan.tasks[0].search.queries[0]
    assert expected[1].casefold().split()[-1] in plan.tasks[1].search.queries[0]


@pytest.mark.asyncio
async def test_analysis_tasks_are_created_only_for_explicit_aggregate_requests() -> None:
    catalog = CollectionCatalog(
        build_fingerprint="a" * 64,
        document_count=10,
        departments=(),
        document_types=("incident",),
        statuses=("final",),
    )
    comparison = await FakeResearchPlanner().create_plan(
        "Compare one incident with another incident.", catalog
    )
    recurring = await FakeResearchPlanner().create_plan(
        "Summarize incidents and identify recurring root causes.", catalog
    )
    assert not any(task.analysis_may_be_useful for task in comparison.tasks)
    assert any(task.analysis_may_be_useful for task in recurring.tasks)
