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
