"""Deterministic offline structured research planner."""

import re
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
        dimensions = _comparison_dimensions(normalized)
        if dimensions:
            domain_terms = _domain_terms(value)
            specs = [
                (
                    ResearchTaskType.COMPARISON_DIMENSION,
                    dimension,
                    " ".join((*_dimension_terms(dimension), *domain_terms, "comparison")),
                )
                for dimension in dimensions
            ]
        elif "policy" in value and "runbook" in value:
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
            ]
            if analysis_requested(value):
                specs.append(
                    (
                        ResearchTaskType.ROOT_CAUSE_ANALYSIS,
                        "Identify recurring root causes",
                        normalized,
                    )
                )
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
                comparison_dimension=objective
                if kind is ResearchTaskType.COMPARISON_DIMENSION and dimensions
                else None,
                comparison_terms=_dimension_terms(objective)
                if kind is ResearchTaskType.COMPARISON_DIMENSION and dimensions
                else (),
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
            required_comparison_dimensions=dimensions,
            completion_criteria=("Authorized evidence supports each available dimension",),
        )


_COMPARE_PREFIX = re.compile(r"^\s*compare(?:\s+the\s+causes?\s+of)?\s+", re.I)
_COMPARE_SEPARATOR = re.compile(r"\s+(?:and|versus|vs\.?)\s+", re.I)
_TOKENS = re.compile(r"[a-z0-9]+")
_TERM_STOP_WORDS = frozenset(
    {"a", "an", "and", "the", "in", "of", "to", "with", "for", "compare", "comparison"}
)


def _comparison_dimensions(question: str) -> tuple[str, ...]:
    if not question.casefold().lstrip().startswith("compare "):
        return ()
    body = _COMPARE_PREFIX.sub("", question).strip(" .?!")
    parts = tuple(
        " ".join(part.split())[:500] for part in _COMPARE_SEPARATOR.split(body) if part.strip()
    )
    return parts if 2 <= len(parts) <= 4 else ()


def _dimension_terms(dimension: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            token
            for token in _TOKENS.findall(dimension.casefold())
            if len(token) > 2 and token not in _TERM_STOP_WORDS
        )
    )[:12]


def _domain_terms(question: str) -> tuple[str, ...]:
    return tuple(
        term for term in ("payment", "incident", "service", "policy", "runbook") if term in question
    )


def analysis_requested(question: str) -> bool:
    return any(
        phrase in question
        for phrase in (
            "count",
            "distribution",
            "frequency",
            "recurring root cause",
            "statistics",
            "aggregate trend",
        )
    )
