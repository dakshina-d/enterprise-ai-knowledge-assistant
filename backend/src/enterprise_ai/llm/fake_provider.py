"""Deterministic credential-free provider for tests and local development."""

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
        elif request.mode is ResponseMode.GROUNDED_RETRIEVAL and request.allowed_evidence_ids:
            evidence_id = request.allowed_evidence_ids[0]
            draft = GroundedAnswerDraft(
                answer_summary="The authorized evidence supports the following response.",
                claims=(
                    GroundedClaim(
                        claim_id="C1",
                        text=(
                            "Consult the cited authorized source for the applicable "
                            "operational guidance."
                        ),
                        supporting_evidence_ids=(evidence_id,),
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
