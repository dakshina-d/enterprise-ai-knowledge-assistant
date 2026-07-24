"""Strict application-owned citation mapping and validation."""

import json
from pathlib import Path

from enterprise_ai.llm.models import (
    CitationValidationResult,
    EvidenceContextItem,
    GroundedAnswerDraft,
    VerifiedCitation,
)
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.security.authorization import AuthorizationService


def validate_citations(
    draft: GroundedAnswerDraft,
    context: tuple[EvidenceContextItem, ...],
    principal: AuthenticatedPrincipal,
    *,
    maximum_citations: int,
    manifest_path: Path = Path("data/processed/ingestion_manifest.json"),
) -> CitationValidationResult:
    mapping = {item.model_id: item for item in context}
    if len(mapping) != len(context):
        return CitationValidationResult(valid=False, errors=("duplicate model evidence ID",))
    expected_build = str(json.loads(manifest_path.read_text(encoding="utf-8"))["build_fingerprint"])
    authorization = AuthorizationService()
    allowed_levels = authorization.allowed_access_levels(principal)
    errors: list[str] = []
    used: list[str] = []
    for claim in draft.claims:
        if claim.factual and not claim.supporting_evidence_ids:
            errors.append(f"{claim.claim_id}: factual claim has no citation")
        for model_id in claim.supporting_evidence_ids:
            item = mapping.get(model_id)
            if item is None:
                errors.append(f"{claim.claim_id}: unknown evidence ID")
                continue
            if item.access_level not in {level.value for level in allowed_levels}:
                errors.append(f"{claim.claim_id}: unauthorized evidence")
            if item.build_fingerprint != expected_build:
                errors.append(f"{claim.claim_id}: stale evidence")
            if item.source_line_start > item.source_line_end:
                errors.append(f"{claim.claim_id}: invalid source line range")
            if model_id not in used:
                used.append(model_id)
    if len(used) > maximum_citations:
        errors.append("citation limit exceeded")
    citations = tuple(
        citation_from_context(mapping[model_id]) for model_id in used if model_id in mapping
    )
    return CitationValidationResult(valid=not errors, errors=tuple(errors), citations=citations)


def citation_from_context(item: EvidenceContextItem) -> VerifiedCitation:
    return VerifiedCitation(
        marker=item.model_id,
        evidence_id=item.evidence_id,
        chunk_id=item.chunk_id,
        document_id=item.document_id,
        title=item.title,
        section=item.section,
        source_file=item.source_file,
        source_line_start=item.source_line_start,
        source_line_end=item.source_line_end,
        version=item.version,
        updated_date=item.updated_date,
        access_level=item.access_level,
        department=item.department,
        document_type=item.document_type,
    )


def validate_identifier_alignment(
    draft: GroundedAnswerDraft,
    validation: CitationValidationResult,
    context: tuple[EvidenceContextItem, ...],
    requirements: tuple[tuple[str, tuple[str, ...]], ...],
) -> CitationValidationResult:
    """Require citations to the authorized primary record for every requested identifier."""
    if not requirements:
        return validation
    context_by_id = {item.model_id: item for item in context}
    cited_ids = {item.marker for item in validation.citations}
    allowed_ids = {model_id for _, model_ids in requirements for model_id in model_ids}
    errors = list(validation.errors)
    for identifier, model_ids in requirements:
        if not model_ids:
            errors.append(
                f"entity_alignment_validation_failed: no authorized evidence for {identifier}"
            )
        elif not cited_ids.intersection(model_ids):
            errors.append(
                f"entity_alignment_validation_failed: requested identifier {identifier} is uncited"
            )
    for claim in draft.claims:
        if not claim.factual:
            continue
        if any(
            model_id not in allowed_ids or model_id not in context_by_id
            for model_id in claim.supporting_evidence_ids
        ):
            errors.append(
                f"{claim.claim_id}: entity_alignment_validation_failed: off-target evidence"
            )
    return validation.model_copy(update={"valid": not errors, "errors": tuple(errors)})
