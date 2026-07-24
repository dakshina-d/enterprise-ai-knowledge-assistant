"""Grounded generation, bounded citation repair, rendering, and fallback."""

import asyncio
import json
import logging
import re

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
)
from enterprise_ai.llm.prompts import (
    append_prompt_section,
    grounded_request,
    research_synthesis_request,
)
from enterprise_ai.llm.provider import LLMProvider
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.observability.tracing import SafeTracer
from enterprise_ai.research.models import ResearchResult
from enterprise_ai.research.planner import analysis_requested
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.security.guardrails import response_policy_violations
from enterprise_ai.tools.python_analysis.models import AnalysisResult

logger = logging.getLogger(__name__)
_FALSE_EVIDENCE_ABSENCE = re.compile(
    r"\b(?:no|without|missing|absent|unsupported|insufficient)\b"
    r"(?:[\w -]{0,40})\b(?:evidence|source|record|document)s?\b"
    r"|\b(?:evidence|source|record|document)s?\b"
    r"(?:[\w -]{0,40})\b(?:missing|absent|unavailable|not found)\b",
    re.IGNORECASE,
)


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
        require_all_evidence_ids: bool = False,
        context_override: tuple[EvidenceContextItem, ...] | None = None,
        comparison_dimensions: tuple[str, ...] = (),
        comparison_evidence_ids: tuple[tuple[str, tuple[str, ...]], ...] = (),
        comparison_shared_facets: tuple[str, ...] = (),
    ) -> tuple[GroundedResponse, GroundedAnswerDraft, CitationValidationResult, int]:
        context = context_override or build_evidence_context(evidence, self.settings)
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
        if comparison_dimensions:
            request = research_synthesis_request(
                question,
                context,
                comparison_dimensions,
                comparison_shared_facets,
                self.settings,
            )
        else:
            request = grounded_request(question, context, self.settings)
        required_evidence_ids = request.allowed_evidence_ids if require_all_evidence_ids else ()
        repairs = 0
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
                if (
                    comparison_dimensions
                    and isinstance(error, LLMInvalidResponseError)
                    and repairs < self.settings.llm_citation_repair_attempts
                    and (maximum_provider_calls is None or repairs + 1 < maximum_provider_calls)
                ):
                    repairs += 1
                    repair = self._grounding_repair_request(
                        request,
                        comparison_dimensions,
                        category="provider_output_rejected",
                    )
                    try:
                        result = await self._generate(repair)
                    except asyncio.CancelledError:
                        raise
                    except Exception as repair_error:
                        if not self.settings.llm_allow_deterministic_fallback:
                            raise
                        fallback = await self._fallback_response(
                            context,
                            self._provider_fallback_reason(repair_error),
                        )
                        return (
                            fallback,
                            GroundedAnswerDraft(answer_summary=fallback.answer_text),
                            CitationValidationResult(
                                valid=True,
                                citations=fallback.citations,
                            ),
                            repairs,
                        )
                else:
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
                        repairs,
                    )
        draft = result.draft
        validation = validate_citations(
            draft,
            context,
            principal,
            maximum_citations=self.settings.llm_max_citations,
            manifest_path=self.settings.ingestion_manifest_path,
        )
        validation, missing_dimensions = _validate_comparison_draft(
            draft,
            validation,
            comparison_evidence_ids,
            comparison_shared_facets,
        )
        validation = _require_citations(validation, required_evidence_ids)
        while (
            not validation.valid
            and repairs < self.settings.llm_citation_repair_attempts
            and (maximum_provider_calls is None or repairs + 1 < maximum_provider_calls)
        ):
            repairs += 1
            repair = self._grounding_repair_request(
                request,
                missing_dimensions,
                category="grounding_validation_failed",
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
            validation, missing_dimensions = _validate_comparison_draft(
                draft,
                validation,
                comparison_evidence_ids,
                comparison_shared_facets,
            )
            validation = _require_citations(validation, required_evidence_ids)
        if not validation.valid:
            if comparison_dimensions:
                fallback = await self._comparison_fallback_response(
                    context,
                    missing_dimensions or comparison_dimensions,
                )
                return fallback, draft, validation, repairs
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
        synthesis_evidence = _comparison_synthesis_evidence(research, evidence)
        comparison_context = (
            build_evidence_context(
                synthesis_evidence,
                self.settings,
                maximum_items=max(
                    self.settings.llm_max_evidence_items,
                    len(synthesis_evidence),
                ),
            )
            if synthesis_evidence
            else ()
        )
        comparison_evidence_ids = _comparison_evidence_ids(research, comparison_context)
        comparison_shared_facets = _comparison_shared_facets(
            research,
            synthesis_evidence,
        )
        response, draft, validation, repairs = await self.retrieval_response(
            question,
            synthesis_evidence or evidence,
            principal,
            maximum_provider_calls=remaining,
            require_all_evidence_ids=bool(synthesis_evidence),
            context_override=comparison_context or None,
            comparison_dimensions=(
                research.plan.required_comparison_dimensions if comparison_context else ()
            ),
            comparison_evidence_ids=comparison_evidence_ids,
            comparison_shared_facets=comparison_shared_facets,
        )
        calls = 0 if remaining == 0 else 1 + repairs
        sections = [response.answer_text]
        relevant_analyses = select_relevant_analyses(question, research.analysis_results)
        if relevant_analyses:
            sections.append(
                "Analysis (calculated from authorized structured rows):\n"
                + "\n".join(result.summary for result in relevant_analyses)
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

    async def _comparison_fallback_response(
        self,
        context: tuple[EvidenceContextItem, ...],
        unvalidated_dimensions: tuple[str, ...],
    ) -> GroundedResponse:
        labels = "; ".join(dict.fromkeys(unvalidated_dimensions))
        answer = (
            "Authorized evidence was supplied for the requested comparison, but a complete "
            "grounded comparison could not be validated."
        )
        if labels:
            answer += f" Unvalidated response dimensions: {labels}."
        async with self.tracer.span(
            "enterprise_ai.deterministic_fallback",
            metadata={
                "fallback_used": True,
                "fallback_reason": FallbackReason.RESEARCH_DIMENSION_VALIDATION_FAILED,
                "evidence_count": len(context),
            },
        ):
            self._log_fallback(FallbackReason.RESEARCH_DIMENSION_VALIDATION_FAILED)
            return GroundedResponse(
                answer_text=answer[: self.settings.llm_max_answer_characters],
                citations=tuple(citation_from_context(item) for item in context),
                provider="deterministic",
                model="none",
                prompt_version="research-1.0",
                deterministic_fallback_used=True,
                fallback_reason=FallbackReason.RESEARCH_DIMENSION_VALIDATION_FAILED,
                insufficient_evidence=True,
                uncertainty="generated_comparison_not_validated",
            )

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

    def _grounding_repair_request(
        self,
        request: LLMGenerationRequest,
        missing_dimensions: tuple[str, ...],
        *,
        category: str,
    ) -> LLMGenerationRequest:
        suffix = (
            "\n\nBOUNDED GROUNDING REPAIR:\n"
            + f"validation_category={category}\n"
            + f"allowed_evidence_ids={json.dumps(request.allowed_evidence_ids)}"
            + "\nmissing_comparison_dimensions="
            + json.dumps(missing_dimensions)
        )
        return request.model_copy(
            update={
                "instructions": (
                    request.instructions
                    + " Grounding validation failed. Return corrected claims and citations "
                    "using only the explicitly allowed evidence IDs. Cover every listed "
                    "missing comparison dimension with its own factual claim when dimensions "
                    "are listed. Do not include reasoning fields or think markup."
                ),
                "input_text": append_prompt_section(
                    request.input_text,
                    suffix,
                    self.settings.llm_max_prompt_characters,
                ),
            }
        )


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


def _require_citations(
    validation: CitationValidationResult,
    required_ids: tuple[str, ...],
) -> CitationValidationResult:
    if not validation.valid or not required_ids:
        return validation
    cited = {item.marker for item in validation.citations}
    missing = tuple(item for item in required_ids if item not in cited)
    if not missing:
        return validation
    return validation.model_copy(
        update={
            "valid": False,
            "errors": (
                *validation.errors,
                "citation_validation_failed: required comparison dimension is uncited",
            ),
        }
    )


def _validate_comparison_draft(
    draft: GroundedAnswerDraft,
    validation: CitationValidationResult,
    requirements: tuple[tuple[str, tuple[str, ...]], ...],
    shared_facets: tuple[str, ...],
) -> tuple[CitationValidationResult, tuple[str, ...]]:
    """Require distinct factual claim coverage for each server-owned comparison dimension."""
    if not requirements:
        return validation, ()
    factual_claims = tuple(claim for claim in draft.claims if claim.factual)
    candidates = tuple(
        tuple(
            index
            for index, claim in enumerate(factual_claims)
            if frozenset(claim.supporting_evidence_ids).intersection(required_ids)
            and _claim_mentions_dimension(claim.text, dimension)
        )
        for dimension, required_ids in requirements
    )
    assigned = _assign_distinct_claims(candidates)
    missing = tuple(
        dimension for index, (dimension, _) in enumerate(requirements) if index not in assigned
    )
    rendered_fields = " ".join(
        (
            draft.answer_summary,
            *(claim.text for claim in draft.claims),
            *draft.warnings,
        )
    )
    falsely_unsupported = bool(
        draft.insufficient_evidence
        or draft.clarification_needed
        or _FALSE_EVIDENCE_ABSENCE.search(rendered_fields)
    )
    comparison_claim_valid = not shared_facets or any(
        all(
            frozenset(claim.supporting_evidence_ids).intersection(required_ids)
            for _, required_ids in requirements
        )
        and all(_text_supports_facet(claim.text, facet) for facet in shared_facets)
        for claim in factual_claims
    )
    errors = list(validation.errors)
    if missing:
        errors.append("research_dimension_validation_failed: comparison dimension is uncovered")
    if falsely_unsupported:
        errors.append(
            "research_dimension_validation_failed: supplied evidence was described as absent"
        )
    if not comparison_claim_valid:
        errors.append(
            "research_dimension_validation_failed: shared comparison facets are uncovered"
        )
    if not errors:
        return validation, ()
    if missing:
        unvalidated = missing
    elif not comparison_claim_valid:
        unvalidated = ("shared comparison conclusion",)
    else:
        unvalidated = tuple(dimension for dimension, _ in requirements)
    return (
        validation.model_copy(update={"valid": False, "errors": tuple(errors)}),
        unvalidated,
    )


def _assign_distinct_claims(candidates: tuple[tuple[int, ...], ...]) -> frozenset[int]:
    assignments: dict[int, int] = {}

    def assign(dimension_index: int, visited: set[int]) -> bool:
        for claim_index in candidates[dimension_index]:
            if claim_index in visited:
                continue
            visited.add(claim_index)
            previous = assignments.get(claim_index)
            if previous is None or assign(previous, visited):
                assignments[claim_index] = dimension_index
                return True
        return False

    covered: set[int] = set()
    for dimension_index in range(len(candidates)):
        if assign(dimension_index, set()):
            covered.add(dimension_index)
    return frozenset(covered)


def _claim_mentions_dimension(text: str, dimension: str) -> bool:
    claim = text.casefold().replace("-", " ")
    terms = tuple(re.findall(r"[a-z0-9]+", dimension.casefold().replace("-", " ")))
    months = {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
    temporal = tuple(term for term in terms if term in months or term.isdigit())
    subject = tuple(
        term
        for term in terms
        if term not in months and not term.isdigit() and term not in {"in", "the", "of", "for"}
    )
    return all(term in claim for term in temporal) and (
        not subject or any(term in claim for term in subject)
    )


def _text_supports_facet(text: str, facet: str) -> bool:
    normalized_text = text.casefold().replace("_", " ").replace("-", " ")
    normalized_facet = facet.casefold().replace("_", " ").replace("-", " ")
    if normalized_facet == "message accumulation":
        return "accumulat" in normalized_text
    return normalized_facet in normalized_text


def _comparison_synthesis_evidence(
    research: ResearchResult,
    evidence: tuple[HybridEvidence, ...],
) -> tuple[HybridEvidence, ...]:
    if (
        not research.plan.required_comparison_dimensions
        or research.coverage.status.value != "sufficient"
    ):
        return ()
    available = {item.evidence.chunk_id for item in evidence}
    selected: list[HybridEvidence] = []
    seen_documents: set[object] = set()
    for dimension in research.plan.required_comparison_dimensions:
        candidates = sorted(
            (
                item
                for result in research.worker_results
                if result.comparison_dimension == dimension
                for item in result.evidence
                if item.evidence.chunk_id in available
            ),
            key=lambda item: (
                item.final_rank,
                -item.hybrid_score,
                str(item.evidence.chunk_id),
            ),
        )
        if not candidates:
            return ()
        choice = next(
            (item for item in candidates if item.evidence.document_id not in seen_documents),
            candidates[0],
        )
        seen_documents.add(choice.evidence.document_id)
        if all(
            existing.evidence.document_id != choice.evidence.document_id for existing in selected
        ):
            selected.append(choice)
    return tuple(selected)


def _comparison_evidence_ids(
    research: ResearchResult,
    context: tuple[EvidenceContextItem, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    by_chunk = {item.chunk_id: item.model_id for item in context}
    by_document = {item.document_id: item.model_id for item in context}
    requirements: list[tuple[str, tuple[str, ...]]] = []
    for dimension in research.plan.required_comparison_dimensions:
        ids = tuple(
            dict.fromkeys(
                model_id
                for result in research.worker_results
                if result.comparison_dimension == dimension
                for evidence in result.evidence
                for model_id in (
                    by_chunk.get(evidence.evidence.chunk_id)
                    or by_document.get(evidence.evidence.document_id),
                )
                if model_id is not None
            )
        )
        if ids:
            requirements.append((dimension, ids))
    return tuple(requirements)


def _comparison_shared_facets(
    research: ResearchResult,
    evidence: tuple[HybridEvidence, ...],
) -> tuple[str, ...]:
    if not research.plan.required_comparison_dimensions or len(evidence) < 2:
        return ()
    texts = tuple(item.evidence.text.casefold() for item in evidence)
    root_causes = []
    normalized_labels = []
    for text in texts:
        matches = set(
            re.findall(
                r"root[\s\S]{0,180}?([a-z][a-z0-9_]*(?:_[a-z0-9]+){2,})",
                text,
            )
        )
        root_causes.append(matches)
        normalized_labels.append(set(re.findall(r"\b[a-z][a-z0-9_]*(?:_[a-z0-9]+){2,}\b", text)))
    shared_causes = set.intersection(*root_causes) if root_causes and all(root_causes) else set()
    if not shared_causes and normalized_labels:
        shared_causes.update(set.intersection(*normalized_labels))
    facets = list(sorted(item for item in shared_causes if len(item) <= 80)[:2])
    if all("throughput" in text for text in texts):
        facets.append("throughput")
    if all("ingress" in text for text in texts):
        facets.append("ingress")
    if all("accumulat" in text for text in texts):
        facets.append("message accumulation")
    return tuple(dict.fromkeys(facets))


def select_relevant_analyses(
    question: str,
    analyses: tuple[AnalysisResult, ...],
) -> tuple[AnalysisResult, ...]:
    """Include typed aggregates only when the user's requested operation calls for them."""
    return analyses if analysis_requested(question.casefold()) else ()
