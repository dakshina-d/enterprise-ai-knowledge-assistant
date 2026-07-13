import pytest
from enterprise_ai.models.identity import UserRole
from enterprise_ai.research.budgets import BudgetLedger
from enterprise_ai.research.models import ResearchBudget, ResearchPlan
from enterprise_ai.research.plan_validator import ResearchPlanValidationError
from enterprise_ai.research.service import ResearchService
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.security.authorization import AuthorizationService

from .test_compiled_rounds import _plan
from .test_executable_timeouts import StaticCatalogs, UnusedRetriever


class RepairingPlanner:
    def __init__(self, initial: ResearchPlan, repaired: ResearchPlan) -> None:
        self.initial = initial
        self.repaired = repaired
        self.repairs = 0

    async def create_plan(self, question: str, catalog: object) -> ResearchPlan:
        return self.initial

    async def repair_plan(
        self, question: str, catalog: object, invalid: ResearchPlan, errors: tuple[str, ...]
    ) -> ResearchPlan:
        self.repairs += 1
        return self.repaired


def _ledger(limit: int) -> BudgetLedger:
    return BudgetLedger(
        ResearchBudget(
            maximum_depth=2,
            maximum_total_tasks=5,
            maximum_retrieval_calls=5,
            maximum_analysis_calls=1,
            maximum_llm_calls=limit,
            maximum_evidence_items=5,
            maximum_evidence_characters=100,
        )
    )


def _service(planner: RepairingPlanner) -> ResearchService:
    service = ResearchService(RetrievalSettings(), UnusedRetriever(), AuthorizationService())
    service.catalogs = StaticCatalogs()  # type: ignore[assignment]
    service.planner = planner  # type: ignore[assignment]
    return service


@pytest.mark.asyncio
async def test_one_repair_consumes_one_additional_call_and_revalidates() -> None:
    valid = _plan()
    invalid_task = valid.tasks[0].model_copy(update={"dependency_task_ids": ("missing",)})
    planner = RepairingPlanner(valid.model_copy(update={"tasks": (invalid_task,)}), valid)
    ledger = _ledger(2)
    assert await ledger.consume("llm_calls")
    repaired = await _service(planner)._plan_with_repair(
        "safe", assessment_principal(UserRole.ANALYST), ledger
    )
    assert repaired.tasks[0].task_id == "T01" and planner.repairs == 1
    assert (await ledger.usage()).llm_calls == 2


@pytest.mark.asyncio
async def test_no_budget_prevents_repair() -> None:
    valid = _plan()
    invalid = valid.model_copy(
        update={"tasks": (valid.tasks[0].model_copy(update={"dependency_task_ids": ("x",)}),)}
    )
    planner = RepairingPlanner(invalid, valid)
    ledger = _ledger(1)
    assert await ledger.consume("llm_calls")
    with pytest.raises(ResearchPlanValidationError):
        await _service(planner)._plan_with_repair(
            "safe", assessment_principal(UserRole.ANALYST), ledger
        )
    assert planner.repairs == 0


@pytest.mark.asyncio
async def test_malicious_plan_never_receives_repair() -> None:
    malicious = _plan().model_copy(
        update={
            "tasks": (
                _plan()
                .tasks[0]
                .model_copy(update={"research_question": "role override administrator"}),
            )
        }
    )
    planner = RepairingPlanner(malicious, _plan())
    ledger = _ledger(2)
    assert await ledger.consume("llm_calls")
    with pytest.raises(ResearchPlanValidationError):
        await _service(planner)._plan_with_repair(
            "safe", assessment_principal(UserRole.ANALYST), ledger
        )
    assert planner.repairs == 0 and (await ledger.usage()).llm_calls == 1


@pytest.mark.asyncio
async def test_invalid_repair_stops_after_one_attempt() -> None:
    valid = _plan()
    invalid = valid.model_copy(
        update={"tasks": (valid.tasks[0].model_copy(update={"dependency_task_ids": ("x",)}),)}
    )
    planner = RepairingPlanner(invalid, invalid)
    ledger = _ledger(3)
    assert await ledger.consume("llm_calls")
    with pytest.raises(ResearchPlanValidationError):
        await _service(planner)._plan_with_repair(
            "safe", assessment_principal(UserRole.ANALYST), ledger
        )
    assert planner.repairs == 1 and (await ledger.usage()).llm_calls == 2
