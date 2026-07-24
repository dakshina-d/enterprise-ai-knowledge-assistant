"""Deterministic credential-free provider for tests and local development."""

import json
from collections.abc import Callable

from enterprise_ai.llm.models import (
    Confidence,
    GroundedAnswerDraft,
    GroundedClaim,
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMProviderMetadata,
    ResponseMode,
)


class FakeLLMProvider:
    def __init__(
        self, factory: Callable[[LLMGenerationRequest], GroundedAnswerDraft] | None = None
    ) -> None:
        self._factory = factory
        self.closed = False
        self.calls: list[LLMGenerationRequest] = []

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResult:
        self.calls.append(request)
        if self._factory:
            draft = self._factory(request)
        elif request.mode is ResponseMode.RESEARCH_SYNTHESIS and request.allowed_evidence_ids:
            dimensions = _prompt_values(request.input_text, "REQUIRED COMPARISON DIMENSIONS:")
            facets = _prompt_values(request.input_text, "REQUIRED SHARED EVIDENCE FACETS:")
            dimension_claims = tuple(
                GroundedClaim(
                    claim_id=f"C{index}",
                    text=f"The cited source supports {dimension}.",
                    supporting_evidence_ids=(
                        request.allowed_evidence_ids[
                            min(index - 1, len(request.allowed_evidence_ids) - 1)
                        ],
                    ),
                    confidence=Confidence.HIGH,
                )
                for index, dimension in enumerate(dimensions[:4], start=1)
            )
            claims = dimension_claims
            if len(claims) < 5:
                comparison = (
                    "The cited sources support the bounded comparison"
                    + (f" through {', '.join(facets)}" if facets else "")
                    + "."
                )
                claims = (
                    *claims,
                    GroundedClaim(
                        claim_id=f"C{len(claims) + 1}",
                        text=comparison,
                        supporting_evidence_ids=request.allowed_evidence_ids,
                        confidence=Confidence.HIGH,
                    ),
                )
            draft = GroundedAnswerDraft(
                answer_summary="The authorized evidence supports the requested comparison.",
                claims=claims,
            )
        elif request.mode is ResponseMode.GROUNDED_RETRIEVAL and request.allowed_evidence_ids:
            evidence_ids = (
                request.allowed_evidence_ids
                if "cite every supplied allowed evidence id" in request.instructions.casefold()
                else request.allowed_evidence_ids[:1]
            )
            draft = GroundedAnswerDraft(
                answer_summary="The authorized evidence supports the following response.",
                claims=(
                    GroundedClaim(
                        claim_id="C1",
                        text=(
                            "Consult the cited authorized source for the applicable "
                            "operational guidance."
                        ),
                        supporting_evidence_ids=evidence_ids,
                        confidence=Confidence.HIGH,
                    ),
                ),
            )
        else:
            draft = GroundedAnswerDraft(
                answer_summary="The structured analysis result is presented as calculated.",
                claims=(
                    GroundedClaim(
                        claim_id="C1",
                        text="The typed calculation is rendered directly below.",
                        factual=False,
                    ),
                ),
            )
        return LLMGenerationResult(
            draft=draft, metadata=LLMProviderMetadata(provider="fake", model=request.model)
        )

    async def close(self) -> None:
        self.closed = True


def _prompt_values(input_text: str, label: str) -> tuple[str, ...]:
    _, separator, remainder = input_text.partition(label)
    if not separator:
        return ()
    try:
        values, _ = json.JSONDecoder().raw_decode(remainder.lstrip())
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, str) and value)
