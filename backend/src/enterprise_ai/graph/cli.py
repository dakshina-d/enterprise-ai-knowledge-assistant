"""Offline command-line entry points for the baseline graph."""

import argparse
import asyncio
from uuid import uuid4

from enterprise_ai.graph.builder import build_graph, describe_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.dependencies import OfflineSparseAdapter
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput
from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.sparse.retriever import SparseRetrievalService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or run the baseline LangGraph")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("describe")
    for command in ("run", "stream"):
        child = subparsers.add_parser(command)
        child.add_argument("message", nargs="?")
        child.add_argument("--query")
        child.add_argument(
            "--role",
            choices=[role.value for role in UserRole],
            default=UserRole.VIEWER.value,
        )
        child.add_argument("--top-k", type=int, default=5)
    return parser


def _runtime(settings: RetrievalSettings) -> GraphRuntime:
    adapter = OfflineSparseAdapter(SparseRetrievalService(settings))
    return GraphRuntime(
        build_graph(settings, adapter, checkpointer=create_checkpointer()), settings
    )


async def _run(arguments: argparse.Namespace) -> None:
    if arguments.command == "describe":
        print(describe_graph().model_dump_json(indent=2))
        return
    message = arguments.query or arguments.message
    if not message:
        raise SystemExit("run and stream require MESSAGE or --query QUERY")
    graph_input = GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(UserRole(arguments.role)),
        user_message=message,
        requested_top_k=arguments.top_k,
    )
    runtime = _runtime(RetrievalSettings())
    if arguments.command == "run":
        print((await runtime.ainvoke(graph_input)).model_dump_json(indent=2))
        return
    async for item in runtime.astream(graph_input):
        print(item.model_dump_json(exclude_none=True))


def main() -> None:
    asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    main()
