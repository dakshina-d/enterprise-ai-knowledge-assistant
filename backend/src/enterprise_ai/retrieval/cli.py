"""Explicit developer CLI for Pinecone index and dense retrieval operations."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.dense_retriever import DenseRetrievalService
from enterprise_ai.retrieval.embeddings import PineconeInferenceEmbeddingProvider
from enterprise_ai.retrieval.evaluation import assessment_principal, evaluate_dense_retrieval
from enterprise_ai.retrieval.filters import DenseQueryFilters
from enterprise_ai.retrieval.indexer import DenseIndexer
from enterprise_ai.retrieval.pinecone_client import PineconeSdkGateway


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pinecone dense retrieval developer utility")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("bootstrap-index")
    commands.add_parser("index")
    commands.add_parser("check-index")
    query = commands.add_parser("query")
    query.add_argument("--role", required=True, choices=[role.value for role in UserRole])
    query.add_argument("--query", required=True)
    query.add_argument("--top-k", type=int, default=None)
    query.add_argument("--department", action="append", default=[])
    query.add_argument("--status", action="append", default=[])
    commands.add_parser("evaluate")
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    settings = RetrievalSettings()
    settings.require_enabled()
    gateway = PineconeSdkGateway(settings)
    embeddings = PineconeInferenceEmbeddingProvider(
        gateway,
        settings.pinecone_dense_model,
        selected_dimension=settings.pinecone_dense_dimension,
        metric=settings.pinecone_metric,
        maximum_input_chars=settings.pinecone_max_embedding_input_chars,
    )
    if args.command in {"bootstrap-index", "index", "check-index"}:
        indexer = DenseIndexer(settings, embeddings, gateway)
        try:
            if args.command == "bootstrap-index":
                dimension = await indexer.bootstrap()
                return {"outcome": "ready", "dimension": dimension}
            if args.command == "index":
                summary = await indexer.index()
            else:
                summary = await indexer.verify()
            return {
                "outcome": "passed",
                "expected_count": summary.expected_count,
                "indexed_count": summary.indexed_count,
                "dimension": summary.dimension,
                "build_fingerprint": summary.build_fingerprint,
            }
        finally:
            await indexer.close()
    retriever = DenseRetrievalService(settings, embeddings, gateway)
    try:
        if args.command == "query":
            result = await retriever.retrieve(
                assessment_principal(UserRole(args.role)),
                args.query,
                top_k=args.top_k,
                filters=DenseQueryFilters(
                    departments=tuple(args.department), statuses=tuple(args.status)
                ),
            )
            return {
                "notice": "Developer utility only; production uses authenticated principals.",
                "results": [
                    {
                        "score": item.dense_score,
                        "title": item.title,
                        "source_file": item.source_file,
                        "section_path": item.section_path,
                        "lines": [item.source_line_start, item.source_line_end],
                    }
                    for item in result.evidence
                ],
            }
        return await evaluate_dense_retrieval(
            retriever,
            questions_path=Path("data/evaluation/research_questions.json"),
            output_path=Path("data/evaluation/results/dense-retrieval-baseline.json"),
        )
    finally:
        await retriever.close()


def main() -> int:
    try:
        result = asyncio.run(_run(_parser().parse_args()))
        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception as error:
        print(f"Dense retrieval command failed safely: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
