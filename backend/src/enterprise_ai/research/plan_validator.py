"""Application-owned research-plan compiler and validation boundary."""

import re
from hashlib import sha256

from enterprise_ai.research.models import ResearchPlan, ResearchTask
from enterprise_ai.retrieval.config import RetrievalSettings

_UNSAFE = re.compile(
    r"(?:https?://|ftp://|file:|[a-zA-Z]:\\|(?:^|[\\/])\.\.[\\/]|/etc/|"
    r"system prompt|role override|permission override|access.level|namespace|"
    r"build.fingerprint|pinecone|python source|python\s*\(|lambda\s|tool name|"
    r"(?:^|\s)(?:rm|del|curl|wget|powershell|cmd\.exe)\s)",
    re.I,
)


class ResearchPlanValidationError(ValueError):
    def __init__(self, message: str, *, repairable: bool = True) -> None:
        super().__init__(message)
        self.repairable = repairable


def compile_plan(plan: ResearchPlan, settings: RetrievalSettings) -> ResearchPlan:
    if len(plan.model_dump_json()) > settings.research_max_plan_characters:
        raise ResearchPlanValidationError("plan size limit exceeded")
    if len(plan.tasks) > settings.research_max_initial_tasks:
        raise ResearchPlanValidationError("initial task limit exceeded")
    unique: dict[tuple[str, tuple[str, ...]], ResearchTask] = {}
    for task in plan.tasks:
        if task.depth > settings.research_max_depth or not task.research_question.strip():
            raise ResearchPlanValidationError("invalid task depth or question")
        if _UNSAFE.search(task.research_question):
            raise ResearchPlanValidationError("unsafe task content", repairable=False)
        if (
            not task.search.queries
            or len(task.search.queries) > settings.research_max_queries_per_task
            or any(
                len(query) > settings.research_max_query_characters or _UNSAFE.search(query)
                for query in task.search.queries
            )
        ):
            unsafe = any(_UNSAFE.search(query) for query in task.search.queries)
            raise ResearchPlanValidationError("invalid search query", repairable=not unsafe)
        key = (
            task.task_type.value,
            tuple(" ".join(q.casefold().split()) for q in task.search.queries),
        )
        unique.setdefault(key, task)
    ordered = sorted(
        unique.values(),
        key=lambda item: (-item.priority, item.task_type.value, item.research_question),
    )
    old_to_new = {item.task_id: f"T{index:02d}" for index, item in enumerate(ordered, 1)}
    known = set(old_to_new)
    compiled = []
    for item in ordered:
        if any(dep not in known for dep in item.dependency_task_ids):
            raise ResearchPlanValidationError("unknown dependency")
        if item.task_id in item.dependency_task_ids:
            raise ResearchPlanValidationError("self dependency")
        compiled.append(
            item.model_copy(
                update={
                    "task_id": old_to_new[item.task_id],
                    "dependency_task_ids": tuple(
                        sorted(old_to_new[dep] for dep in item.dependency_task_ids)
                    ),
                }
            )
        )
    _reject_cycles(tuple(compiled))
    digest = sha256(
        (
            plan.normalized_objective
            + "|"
            + "|".join(t.task_id + t.research_question for t in compiled)
        ).encode()
    ).hexdigest()[:12]
    return plan.model_copy(
        update={
            "plan_id": f"RP-{digest}",
            "tasks": tuple(compiled),
            "maximum_depth": settings.research_max_depth,
            "maximum_tasks": settings.research_max_total_tasks,
        }
    )


def _reject_cycles(tasks: tuple[ResearchTask, ...]) -> None:
    edges = {task.task_id: task.dependency_task_ids for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ResearchPlanValidationError("dependency cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in edges[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in edges:
        visit(task_id)
