"""Grounded generation, bounded citation repair, rendering, and fallback."""

import re

from enterprise_ai.llm.citation_validator import citation_from_context, validate_citations
from enterprise_ai.llm.grounding import build_evidence_context
from enterprise_ai.llm.models import (
    CitationValidationResult,
    EvidenceContextItem,
    GroundedAnswerDraft,
    GroundedResponse,
    LLMGenerationRequest,
    ResponseMode,
)
from enterprise_ai.llm.prompts import analysis_request, grounded_request
from enterprise_ai.llm.provider import LLMProvider
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.tools.python_analysis.models import AnalysisResult

_UNSAFE = re.compile(r"<\s*script|https?://", re.I)


class GroundedResponseService:
    def __init__(self, provider: LLMProvider, settings: RetrievalSettings) -> None:
        self.provider = provider
        self.settings = settings

    async def close(self) -> None:
        await self.provider.close()

    async def retrieval_response(
        self, question: str, evidence: tuple[HybridEvidence, ...], principal: AuthenticatedPrincipal
    ) -> tuple[GroundedResponse, GroundedAnswerDraft, CitationValidationResult, int]:
        context = build_evidence_context(evidence, self.settings)
        if not context:
            response = GroundedResponse(
                answer_text="No sufficient authorized evidence was found for this request.",
                provider="deterministic",
                model="none",
                prompt_version="1.0",
                deterministic_fallback_used=True,
                insufficient_evidence=True,
                uncertainty="insufficient_evidence",
            )
            return (
                response,
                GroundedAnswerDraft(
                    answer_summary=response.answer_text, insufficient_evidence=True
                ),
                CitationValidationResult(valid=True),
                0,
            )
        request = grounded_request(question, context, self.settings)
        result = await self.provider.generate(request)
        draft = result.draft
        validation = validate_citations(
            draft,
            context,
            principal,
            maximum_citations=self.settings.llm_max_citations,
            manifest_path=self.settings.ingestion_manifest_path,
        )
        repairs = 0
        while not validation.valid and repairs < self.settings.llm_citation_repair_attempts:
            repairs += 1
            repair = LLMGenerationRequest(
                mode=ResponseMode.GROUNDED_RETRIEVAL,
                instructions=request.instructions
                + " Return corrected citations using only the allowed IDs.",
                input_text=(
                    request.input_text + "\nVALIDATION FAILURES:\n" + "; ".join(validation.errors)
                )[: self.settings.llm_max_prompt_characters],
                allowed_evidence_ids=request.allowed_evidence_ids,
                model=request.model,
                maximum_output_tokens=request.maximum_output_tokens,
            )
            draft = (await self.provider.generate(repair)).draft
            validation = validate_citations(
                draft,
                context,
                principal,
                maximum_citations=self.settings.llm_max_citations,
                manifest_path=self.settings.ingestion_manifest_path,
            )
        if not validation.valid:
            return self._evidence_fallback(context), draft, validation, repairs
        answer = render_draft(draft)
        if _UNSAFE.search(answer):
            return (
                self._evidence_fallback(context),
                draft,
                CitationValidationResult(valid=False, errors=("unsafe output content",)),
                repairs,
            )
        return (
            GroundedResponse(
                answer_text=answer[: self.settings.llm_max_answer_characters],
                citations=validation.citations,
                provider=result.metadata.provider,
                model=result.metadata.model,
                prompt_version="1.0",
                insufficient_evidence=draft.insufficient_evidence,
            ),
            draft,
            validation,
            repairs,
        )

    async def analysis_response(self, question: str, analysis: AnalysisResult) -> GroundedResponse:
        request = analysis_request(question, analysis, self.settings)
        result = await self.provider.generate(request)
        # Typed calculations are rendered deterministically to prevent numerical drift.
        return GroundedResponse(
            answer_text=analysis.summary[: self.settings.llm_max_answer_characters],
            provider=result.metadata.provider,
            model=result.metadata.model,
            prompt_version="1.0",
            deterministic_fallback_used=True,
        )

    def _evidence_fallback(self, context: tuple[EvidenceContextItem, ...]) -> GroundedResponse:
        items = context[:3]
        text = "Authorized evidence was found: " + "; ".join(
            f"{item.title} ({item.section}) [{item.model_id}]" for item in items
        )
        return GroundedResponse(
            answer_text=text,
            citations=tuple(citation_from_context(item) for item in items),
            provider="deterministic",
            model="none",
            prompt_version="1.0",
            deterministic_fallback_used=True,
        )


def render_draft(draft: GroundedAnswerDraft) -> str:
    paragraphs = [draft.answer_summary]
    for claim in draft.claims:
        markers = "".join(f"[{item}]" for item in dict.fromkeys(claim.supporting_evidence_ids))
        paragraphs.append(f"{claim.text} {markers}".rstrip())
    return "\n\n".join(paragraphs)
