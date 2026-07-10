"""Command-line interface for deterministic offline ingestion."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from enterprise_ai_ingestion.config import IngestionConfig, default_config
from enterprise_ai_ingestion.exceptions import IngestionError
from enterprise_ai_ingestion.pipeline import IngestionPipeline


def parser() -> argparse.ArgumentParser:
    defaults = default_config()
    command = argparse.ArgumentParser(prog="enterprise_ai_ingestion")
    command.add_argument("command", choices=("build", "check", "validate"))
    command.add_argument("--source-root", type=Path, default=defaults.source_root)
    command.add_argument("--output-root", type=Path, default=defaults.output_root)
    command.add_argument("--target-chunk-tokens", type=int, default=450)
    command.add_argument("--maximum-chunk-tokens", type=int, default=650)
    command.add_argument("--overlap-tokens", type=int, default=75)
    command.add_argument("--minimum-chunk-tokens", type=int, default=80)
    command.add_argument("--concurrency", type=int, default=8)
    return command


def main(arguments: Sequence[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    try:
        config = IngestionConfig(
            source_root=args.source_root,
            output_root=args.output_root,
            target_chunk_tokens=args.target_chunk_tokens,
            maximum_chunk_tokens=args.maximum_chunk_tokens,
            overlap_tokens=args.overlap_tokens,
            minimum_chunk_tokens=args.minimum_chunk_tokens,
            concurrency=args.concurrency,
        )
        pipeline = IngestionPipeline(config)
        if args.command == "build":
            bundle = asyncio.run(pipeline.build())
        elif args.command == "check":
            bundle = asyncio.run(pipeline.check())
        else:
            bundle = asyncio.run(pipeline.validate())
    except (IngestionError, ValidationError, OSError, ExceptionGroup) as error:
        print(f"Ingestion {args.command} failed: {_safe_error(error)}", file=sys.stderr)
        return 1
    print(
        f"Ingestion {args.command} passed: {bundle.manifest.document_count} documents, "
        f"{bundle.manifest.chunk_count} chunks."
    )
    return 0


def _safe_error(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(_safe_error(item) for item in error.exceptions)
    return f"{type(error).__name__}: {error}"
