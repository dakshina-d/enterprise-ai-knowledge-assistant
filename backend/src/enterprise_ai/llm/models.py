"""Strict grounded-response provider and public validation contracts."""

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from enterprise_ai.models.common import ContractModel


class ResponseMode(StrEnum):
    GROUNDED_RETRIEVAL = "grounded_retrieval"
    RESEARCH_SYNTHESIS = "research_synthesis"
    STRUCTURED_ANALYSIS = "structured_analysis"
    DIRECT = "direct"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FallbackReason(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_HTTP_ERROR = "provider_http_error"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    PROHIBITED_REASONING = "prohibited_reasoning"
    CITATION_VALIDATION_FAILED = "citation_validation_failed"
    ENTITY_ALIGNMENT_VALIDATION_FAILED = "entity_alignment_validation_failed"
    RESEARCH_DIMENSION_VALIDATION_FAILED = "research_dimension_validation_failed"
    RESPONSE_POLICY_REJECTED = "response_policy_rejected"
    PROVIDER_CALL_BUDGET_EXHAUSTED = "provider_call_budget_exhausted"
    UNKNOWN_PROVIDER_FAILURE = "unknown_provider_failure"


class GroundedClaim(ContractModel):
    claim_id: Annotated[str, Field(pattern=r"^C[1-9][0-9]{0,2}$")]
    text: Annotated[str, Field(min_length=1, max_length=2_000, repr=False)]
    supporting_evidence_ids: tuple[Annotated[str, Field(pattern=r"^E[1-9][0-9]{0,2}$")], ...] = ()
    factual: bool = True
    confidence: Confidence = Confidence.MEDIUM
    qualification: Annotated[str | None, Field(max_length=500)] = None

    @model_validator(mode="after")
    def factual_citations(self) -> Self:
        if self.factual and not self.supporting_evidence_ids:
            raise ValueError("factual claims require evidence IDs")
        return self


class GroundedAnswerDraft(ContractModel):
    answer_summary: Annotated[str, Field(min_length=1, max_length=8_000, repr=False)]
    claims: tuple[GroundedClaim, ...] = Field(default=(), max_length=20)
    warnings: tuple[Annotated[str, Field(max_length=500)], ...] = ()
    insufficient_evidence: bool = False
    clarification_needed: bool = False


class LLMUsage(ContractModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class LLMProviderMetadata(ContractModel):
    provider: str
    model: str
    response_id: str | None = None


class LLMGenerationRequest(ContractModel):
    mode: ResponseMode
    instructions: str = Field(repr=False)
    input_text: str = Field(repr=False)
    allowed_evidence_ids: tuple[str, ...] = ()
    required_claim_count: int | None = Field(default=None, ge=1, le=5)
    model: str
    maximum_output_tokens: int


class LLMGenerationResult(ContractModel):
    draft: GroundedAnswerDraft
    metadata: LLMProviderMetadata
    usage: LLMUsage = Field(default_factory=LLMUsage)


class EvidenceContextItem(ContractModel):
    model_id: str
    evidence_id: UUID
    chunk_id: UUID
    document_id: UUID
    title: str
    document_type: str
    department: str
    status: str
    version: str
    updated_date: str
    section: str
    source_file: str
    source_line_start: int
    source_line_end: int
    access_level: str
    text: str
    build_fingerprint: str


class VerifiedCitation(ContractModel):
    marker: str
    evidence_id: UUID
    chunk_id: UUID
    document_id: UUID
    title: str
    section: str
    source_file: str
    source_line_start: int
    source_line_end: int
    version: str
    updated_date: str
    access_level: str
    department: str
    document_type: str


class CitationValidationResult(ContractModel):
    valid: bool
    errors: tuple[str, ...] = ()
    citations: tuple[VerifiedCitation, ...] = ()


class GroundedResponse(ContractModel):
    answer_text: str
    citations: tuple[VerifiedCitation, ...] = ()
    provider: str
    model: str
    prompt_version: str
    deterministic_fallback_used: bool = False
    deterministic_analysis_rendering_used: bool = False
    fallback_reason: FallbackReason | None = None
    insufficient_evidence: bool = False
    uncertainty: str | None = None

    @model_validator(mode="after")
    def deterministic_rendering_is_not_fallback(self) -> Self:
        if self.deterministic_analysis_rendering_used and (
            self.deterministic_fallback_used or self.fallback_reason is not None
        ):
            raise ValueError("successful deterministic analysis cannot be a fallback")
        return self
