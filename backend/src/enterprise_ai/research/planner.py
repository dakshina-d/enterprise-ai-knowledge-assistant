"""Deterministic offline structured research planner."""

from hashlib import sha256

from enterprise_ai.research.models import (
    CollectionCatalog,
    ResearchPlan,
    ResearchSearchStrategy,
    ResearchTask,
    ResearchTaskType,
)
from enterprise_ai.retrieval.filters import DenseQueryFilters


class FakeResearchPlanner:
    async def create_plan(self, question: str, catalog: CollectionCatalog) -> ResearchPlan:
        normalized = " ".join(question.split())
        value = normalized.casefold()
        specs: list[tuple[ResearchTaskType, str, str]]
        if "policy" in value and "runbook" in value:
            specs = [
                (
                    ResearchTaskType.POLICY_LOOKUP,
                    "Approved policy requirements",
                    "approved payment failover policy",
                ),
                (
                    ResearchTaskType.RUNBOOK_LOOKUP,
                    "Active operational instructions",
                    "active payment failover runbook",
                ),
                (
                    ResearchTaskType.COMPARISON_DIMENSION,
                    "Compare authority and operational guidance",
                    "payment failover policy runbook differences",
                ),
            ]
        elif "architecture" in value:
            specs = [
                (ResearchTaskType.ARCHITECTURE_LOOKUP, "Find architecture decisions", normalized),
                (
                    ResearchTaskType.TIMELINE_LOOKUP,
                    "Establish change timeline",
                    f"{normalized} timeline",
                ),
            ]
        else:
            specs = [
                (ResearchTaskType.INCIDENT_LOOKUP, "Find relevant incidents", normalized),
                (
                    ResearchTaskType.ROOT_CAUSE_ANALYSIS,
                    "Identify recurring root causes",
                    "payment incident root cause",
                ),
                (
                    ResearchTaskType.COMPARISON_DIMENSION,
                    "Compare recovery actions",
                    "payment incident recovery corrective action",
                ),
            ]
        tasks = tuple(
            ResearchTask(
                task_id=f"T{index}",
                depth=0,
                task_type=kind,
                research_question=objective,
                search=ResearchSearchStrategy(queries=(query,), filters=DenseQueryFilters()),
                priority=100 - index,
                analysis_may_be_useful=kind
                in {
                    ResearchTaskType.ROOT_CAUSE_ANALYSIS,
                    ResearchTaskType.FREQUENCY_ANALYSIS,
                },
                completion_criteria=("At least one authorized source",),
            )
            for index, (kind, objective, query) in enumerate(specs, 1)
        )
        digest = sha256(normalized.encode()).hexdigest()[:12]
        return ResearchPlan(
            plan_id=f"RP-{digest}",
            original_question=question,
            normalized_objective=normalized,
            research_scope="authorized enterprise collection",
            authorized_collection_summary=catalog,
            tasks=tasks,
            expected_synthesis_dimensions=tuple(item[1] for item in specs),
            required_comparison_dimensions=("source authority",) if "compare" in value else (),
            completion_criteria=("Authorized evidence supports each available dimension",),
        )
