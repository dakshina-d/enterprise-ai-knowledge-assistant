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
