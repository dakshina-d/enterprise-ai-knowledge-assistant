"""Safe offline research planning and execution CLI."""

import argparse
import asyncio
import json
from uuid import uuid4

from enterprise_ai.graph.dependencies import OfflineSparseAdapter
from enterprise_ai.graph.routing import requests_inaccessible_access
from enterprise_ai.models.identity import UserRole
from enterprise_ai.research.evaluation import evaluate_research, security_integrity_failures
from enterprise_ai.research.models import ResearchRequest
from enterprise_ai.research.service import ResearchService
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.sparse.retriever import SparseRetrievalService
from enterprise_ai.security.authorization import AuthorizationService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or run bounded recursive research")
    parser.add_argument("command", choices=("plan", "run", "evaluate"))
    parser.add_argument("--role", choices=[role.value for role in UserRole], default="viewer")
    parser.add_argument("--query")
    return parser


async def _run(args: argparse.Namespace) -> None:
    settings = RetrievalSettings()
    principal = assessment_principal(UserRole(args.role))
    service = ResearchService(
        settings, OfflineSparseAdapter(SparseRetrievalService(settings)), AuthorizationService()
    )
    if args.command == "evaluate":
        report = await evaluate_research(settings)
        print(json.dumps(report, indent=2))
        failures = security_integrity_failures(report)
        if failures:
            raise SystemExit("security integrity failures: " + ", ".join(failures))
        return
    if not args.query:
        raise SystemExit("plan and run require --query")
    if requests_inaccessible_access(args.query, principal, service.authorization):
        print(
            json.dumps(
                {
                    "completion_status": "blocked_by_authorization",
                    "message": "Your role does not permit this request.",
                },
                indent=2,
            )
        )
        return
    if args.command == "plan":
        plan = await service.plan(args.query, principal)
        safe = {
            "plan_id": plan.plan_id,
            "normalized_objective": plan.normalized_objective,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "type": task.task_type,
                    "queries": task.search.queries,
                    "dependencies": task.dependency_task_ids,
                    "depth": task.depth,
                }
                for task in plan.tasks
            ],
            "maximum_depth": plan.maximum_depth,
            "maximum_tasks": plan.maximum_tasks,
        }
        print(json.dumps(safe, indent=2))
        return
    identifier = uuid4()
    result = await service.run(
        ResearchRequest(
            question=args.query,
            principal=principal,
            request_id=identifier,
            trace_id=uuid4(),
            session_id=uuid4(),
        )
    )
    print(
        result.model_dump_json(
            indent=2,
            exclude={
                "evidence_ledger": {"entries": {"__all__": {"evidence": {"evidence": {"text"}}}}}
            },
        )
    )


def main() -> None:
    asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    main()
