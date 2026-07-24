"""Grounded generation, bounded citation repair, rendering, and fallback."""

import asyncio
import json
import logging

from pydantic import ValidationError

from enterprise_ai.llm.citation_validator import citation_from_context, validate_citations
from enterprise_ai.llm.exceptions import (
    LLMDependencyUnavailableError,
    LLMHTTPStatusError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRefusalError,
    LLMTimeoutError,
)
from enterprise_ai.llm.grounding import build_evidence_context
from enterprise_ai.llm.models import (
    CitationValidationResult,
    EvidenceContextItem,
    FallbackReason,
    GroundedAnswerDraft,
    GroundedResponse,
    LLMGenerationRequest,
    LLMGenerationResult,
    ResponseMode,
)
from enterprise_ai.llm.prompts import grounded_request
from enterprise_ai.llm.provider import LLMProvider
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.observability.tracing import SafeTracer
from enterprise_ai.research.models import ResearchResult
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.security.guardrails import response_policy_violations
from enterprise_ai.tools.python_analysis.models import AnalysisResult

logger = logging.getLogger(__name__)


class GroundedResponseService:
    def __init__(
        self,
        provider: LLMProvider,
        settings: RetrievalSettings,
        tracer: SafeTracer | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.tracer = tracer or SafeTracer()

    async def close(self) -> None:
        await self.provider.close()

    async def retrieval_response(
        self,
        question: str,
        evidence: tuple[HybridEvidence, ...],
        principal: AuthenticatedPrincipal,
        *,
        maximum_provider_calls: int | None = None,
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
        if maximum_provider_calls is not None and maximum_provider_calls <= 0:
            fallback = await self._fallback_response(
                context,
                FallbackReason.PROVIDER_CALL_BUDGET_EXHAUSTED,
            )
            return (
                fallback,
                GroundedAnswerDraft(answer_summary=fallback.answer_text),
                CitationValidationResult(valid=True, citations=fallback.citations),
                0,
            )
        request = grounded_request(question, context, self.settings)
        async with self.tracer.span(
            "enterprise_ai.llm.generate",
            "llm",
            {"model": request.model, "llm_calls": 1},
        ):
            try:
                result = await self._generate(request)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not self.settings.llm_allow_deterministic_fallback:
                    raise
                fallback = await self._fallback_response(
                    context,
                    self._provider_fallback_reason(error),
                )
                return (
                    fallback,
                    GroundedAnswerDraft(answer_summary=fallback.answer_text),
                    CitationValidationResult(valid=True, citations=fallback.citations),
                    0,
                )
        draft = result.draft
        validation = validate_citations(
            draft,
            context,
            principal,
            maximum_citations=self.settings.llm_max_citations,
            manifest_path=self.settings.ingestion_manifest_path,
        )
        repairs = 0
        while (
            not validation.valid
            and repairs < self.settings.llm_citation_repair_attempts
            and (maximum_provider_calls is None or repairs + 1 < maximum_provider_calls)
        ):
            repairs += 1
            repair = LLMGenerationRequest(
                mode=ResponseMode.GROUNDED_RETRIEVAL,
                instructions=request.instructions
                + " Citation validation failed. Return corrected citations using only the "
                "explicitly allowed evidence IDs.",
                input_text=(
                    request.input_text
                    + "\n\nCITATION REPAIR:\n"
                    + "validation_category=citation_validation_failed\n"
                    + f"allowed_evidence_ids={json.dumps(request.allowed_evidence_ids)}"
                )[: self.settings.llm_max_prompt_characters],
                allowed_evidence_ids=request.allowed_evidence_ids,
                model=request.model,
                maximum_output_tokens=request.maximum_output_tokens,
            )
            async with self.tracer.span(
                "enterprise_ai.citation_repair",
                "llm",
                {"model": repair.model, "llm_calls": repairs + 1},
            ):
                try:
                    draft = (await self._generate(repair)).draft
                except asyncio.CancelledError:
                    raise
                except Exception:
                    fallback = await self._fallback_response(
                        context,
                        FallbackReason.CITATION_VALIDATION_FAILED,
                    )
                    return fallback, draft, validation, repairs
            validation = validate_citations(
                draft,
                context,
                principal,
                maximum_citations=self.settings.llm_max_citations,
                manifest_path=self.settings.ingestion_manifest_path,
            )
        if not validation.valid:
            fallback = await self._fallback_response(
                context,
                FallbackReason.CITATION_VALIDATION_FAILED,
            )
            return fallback, draft, validation, repairs
        answer = render_draft(draft)
        violations = response_policy_violations(answer)
        if violations:
            fallback = await self._fallback_response(
                context,
                FallbackReason.RESPONSE_POLICY_REJECTED,
            )
            return (
                fallback,
                draft,
                CitationValidationResult(
                    valid=False,
                    errors=tuple(f"response policy: {code}" for code in violations),
                ),
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
        # The model cannot add value here without risking drift from the verified typed result.
        del question
        return GroundedResponse(
            answer_text=render_analysis_result(analysis)[: self.settings.llm_max_answer_characters],
            provider="deterministic",
            model="typed-analysis",
            prompt_version="analysis-1.0",
            deterministic_analysis_rendering_used=True,
        )

    async def research_response(
        self,
        question: str,
        evidence: tuple[HybridEvidence, ...],
        principal: AuthenticatedPrincipal,
        research: ResearchResult,
    ) -> tuple[GroundedResponse, GroundedAnswerDraft, CitationValidationResult, int, int]:
        """Synthesize citations normally and render typed calculations deterministically."""
        remaining = max(
            0,
            self.settings.research_max_llm_calls - research.budget_usage.llm_calls,
        )
        response, draft, validation, repairs = await self.retrieval_response(
            question,
            evidence,
            principal,
            maximum_provider_calls=remaining,
        )
        calls = 0 if remaining == 0 else 1 + repairs
        sections = [response.answer_text]
        if research.analysis_results:
            sections.append(
                "Analysis (calculated from authorized structured rows):\n"
                + "\n".join(result.summary for result in research.analysis_results)
            )
        if research.conflicts:
            sections.append(
                "Material conflicts:\n" + "\n".join(item.description for item in research.conflicts)
            )
        if research.structured_conflicts:
            sections.append(
                "Structured conflicts:\n"
                + "\n".join(item.warning for item in research.structured_conflicts)
            )
        if research.gaps:
            sections.append("Limitations:\n" + "\n".join(item.dimension for item in research.gaps))
        if research.budget_usage.exhausted:
            sections.append("Limitations:\nThe server-owned research budget was exhausted.")
        answer = "\n\n".join(sections)[: self.settings.llm_max_answer_characters]
        return (
            response.model_copy(update={"answer_text": answer}),
            draft,
            validation,
            repairs,
            calls,
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

    async def _fallback_response(
        self,
        context: tuple[EvidenceContextItem, ...],
        reason: FallbackReason,
    ) -> GroundedResponse:
        async with self.tracer.span(
            "enterprise_ai.deterministic_fallback",
            metadata={
                "fallback_used": True,
                "fallback_reason": reason,
                "evidence_count": len(context),
            },
        ):
            self._log_fallback(reason)
            return self._evidence_fallback(context).model_copy(update={"fallback_reason": reason})

    @staticmethod
    def _log_fallback(reason: FallbackReason) -> None:
        logger.info(
            "llm_deterministic_fallback",
            extra={"fallback_reason": reason.value, "fallback_used": True},
        )

    @staticmethod
    def _provider_fallback_reason(error: Exception) -> FallbackReason:
        if isinstance(error, LLMDependencyUnavailableError):
            return FallbackReason.PROVIDER_UNAVAILABLE
        if isinstance(error, (LLMTimeoutError, TimeoutError)):
            return FallbackReason.PROVIDER_TIMEOUT
        if isinstance(error, LLMHTTPStatusError):
            return FallbackReason.PROVIDER_HTTP_ERROR
        if isinstance(error, LLMInvalidResponseError):
            if error.category == "prohibited_reasoning":
                return FallbackReason.PROHIBITED_REASONING
            return FallbackReason.INVALID_STRUCTURED_OUTPUT
        if isinstance(error, (LLMRefusalError, ValidationError)):
            return FallbackReason.INVALID_STRUCTURED_OUTPUT
        if isinstance(error, LLMProviderError):
            return FallbackReason.UNKNOWN_PROVIDER_FAILURE
        return FallbackReason.UNKNOWN_PROVIDER_FAILURE

    async def _generate(self, request: LLMGenerationRequest) -> LLMGenerationResult:
        async with asyncio.timeout(self.settings.selected_llm_timeout_seconds()):
            result = await self.provider.generate(request)
        return LLMGenerationResult.model_validate(result)


def render_draft(draft: GroundedAnswerDraft) -> str:
    paragraphs = [draft.answer_summary]
    for claim in draft.claims:
        markers = "".join(f"[{item}]" for item in dict.fromkeys(claim.supporting_evidence_ids))
        paragraphs.append(f"{claim.text} {markers}".rstrip())
    return "\n\n".join(paragraphs)


def render_analysis_result(result: AnalysisResult) -> str:
    """Render only verified typed values; result items are already server-limit bounded."""
    sections = [result.summary]
    if result.items:
        label = "Root cause" if result.operation.value == "recurring_root_causes" else "Category"
        rows = [f"| {label} | Count | Supporting incidents |", "|---|---:|---|"]
        rows.extend(
            "| {key} | {count} | {incidents} |".format(
                key=_markdown_cell(item.key),
                count=item.count,
                incidents=", ".join(_markdown_cell(value) for value in item.incident_ids) or "—",
            )
            for item in result.items
        )
        sections.append("\n".join(rows))
    elif result.scalar_value is not None:
        sections.append(f"Result: {result.scalar_value}")
    elif result.statistics:
        rows = ["| Statistic | Value |", "|---|---:|"]
        rows.extend(
            f"| {_markdown_cell(name)} | {value} |" for name, value in result.statistics.items()
        )
        sections.append("\n".join(rows))
    provenance = [
        f"- Operation: `{result.operation.value}`",
        f"- Authorized rows considered: {result.row_count_considered}",
        f"- Rows excluded: {result.row_count_excluded}",
        f"- Algorithm version: `{_markdown_cell(result.provenance.algorithm_version)}`",
    ]
    if result.provenance.taxonomy_version is not None:
        provenance.append(
            f"- Taxonomy version: `{_markdown_cell(result.provenance.taxonomy_version)}`"
        )
    sections.append("Provenance\n" + "\n".join(provenance))
    return "\n\n".join(sections)


def _markdown_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\r", " ").replace("\n", " ")
