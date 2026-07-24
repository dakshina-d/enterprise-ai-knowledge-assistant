"""Safe developer checks for configured LLM providers."""

from __future__ import annotations

import argparse
import asyncio
import json
from time import monotonic

from enterprise_ai.llm.exceptions import LLMHTTPStatusError, LLMInvalidResponseError
from enterprise_ai.llm.models import LLMGenerationRequest, ResponseMode
from enterprise_ai.llm.ollama_provider import OllamaChatProvider
from enterprise_ai.retrieval.config import RetrievalSettings


class OllamaCheckError(RuntimeError):
    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__("Ollama readiness check failed safely")


async def _check_ollama(settings: RetrievalSettings) -> dict[str, object]:
    provider = OllamaChatProvider(settings)
    started = monotonic()
    try:
        try:
            version = await provider.version()
        except Exception as error:
            raise OllamaCheckError("version") from error
        try:
            models = await provider.model_names()
        except Exception as error:
            raise OllamaCheckError("models") from error
        if settings.ollama_model not in models:
            raise OllamaCheckError("model_missing")
        try:
            result = await provider.generate(
                LLMGenerationRequest(
                    mode=ResponseMode.GROUNDED_RETRIEVAL,
                    instructions=(
                        "Return one concise factual claim with claim_id C1, "
                        "supporting_evidence_ids containing only E1, and confidence high. "
                        "Return no warnings, set both boolean fields false, and do not "
                        "include private reasoning."
                    ),
                    input_text=(
                        "USER QUESTION: Is the local provider ready? "
                        "UNTRUSTED EVIDENCE E1: The local readiness probe is available."
                    ),
                    allowed_evidence_ids=("E1",),
                    model=settings.ollama_model,
                    maximum_output_tokens=min(settings.ollama_num_predict, 128),
                )
            )
        except Exception as error:
            raise OllamaCheckError("structured_generation") from error
    finally:
        await provider.close()
    elapsed = monotonic() - started
    return {
        "status": "ready",
        "ollama_version": version,
        "model": settings.ollama_model,
        "elapsed_seconds": round(elapsed, 2),
        "output_tokens": result.usage.output_tokens,
        "structured_output_valid": True,
        "thinking_empty": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-ollama")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "check-ollama":
            result = asyncio.run(_check_ollama(RetrievalSettings()))
        else:
            raise RuntimeError("unsupported LLM check")
    except OllamaCheckError as error:
        cause: BaseException | None = error.__cause__
        status = None
        category = None
        failure_type = None
        while cause is not None:
            failure_type = type(cause).__name__
            if isinstance(cause, LLMInvalidResponseError):
                category = cause.category
            if isinstance(cause, LLMHTTPStatusError):
                status = cause.status_code
                category = cause.category
                break
            cause = cause.__cause__
        suffix = f" (HTTP {status}, category={category})" if status is not None else ""
        if status is None and failure_type is not None:
            suffix = f" (category={category or failure_type})"
        print(f"LLM check failed safely at stage: {error.stage}{suffix}")
        return 1
    except Exception as error:
        print(f"LLM check failed safely: {type(error).__name__}")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
