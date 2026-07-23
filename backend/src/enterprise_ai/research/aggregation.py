"""Deterministic immutable research evidence aggregation."""

from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.models.retrieval import DocumentMetadata
from enterprise_ai.research.models import (
    ResearchEvidenceEntry,
    ResearchEvidenceLedger,
    ResearchWorkerResult,
)
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.security.guardrails import contains_untrusted_instruction


def aggregate_evidence(
    results: tuple[ResearchWorkerResult, ...],
    *,
    maximum_items: int,
    maximum_characters: int,
    expected_build_fingerprint: str | None = None,
    principal: AuthenticatedPrincipal | None = None,
    authorization: AuthorizationService | None = None,
) -> ResearchEvidenceLedger:
    collected: dict[object, ResearchEvidenceEntry] = {}
    evidence_to_chunk: dict[object, object] = {}
    dropped = 0
    for result in sorted(results, key=lambda item: item.task_id):
        for evidence in result.evidence:
            key = evidence.evidence.chunk_id
            source = evidence.evidence
            if (
                expected_build_fingerprint
                and source.build_fingerprint != expected_build_fingerprint
            ):
                dropped += 1
                continue
            if contains_untrusted_instruction(source.text):
                dropped += 1
                continue
            if principal is not None:
                policy = authorization or AuthorizationService()
                metadata = DocumentMetadata(
                    document_id=source.document_id,
                    title=source.title,
                    source=source.source,
                    department=source.department,
                    document_type=source.document_type,
                    access_level=source.access_level,
                    allowed_roles=source.allowed_roles,
                    created_date=source.updated_date,
                    updated_date=source.updated_date,
                    version=source.version,
                    content_hash=source.chunk_content_hash,
                )
                if not policy.is_document_authorized(principal, metadata):
                    dropped += 1
                    continue
            known_chunk = evidence_to_chunk.get(source.evidence_id)
            if known_chunk is not None and known_chunk != key:
                dropped += 1
                continue
            existing = collected.get(key)
            if existing is not None:
                current = existing.evidence.evidence
                identity = (
                    "evidence_id",
                    "document_id",
                    "source_file",
                    "section_path",
                    "source_line_start",
                    "source_line_end",
                    "title",
                    "version",
                    "updated_date",
                    "access_level",
                    "allowed_roles",
                    "chunk_content_hash",
                    "build_fingerprint",
                )
                if any(getattr(current, field) != getattr(source, field) for field in identity):
                    dropped += 1
                    continue
                best = min(
                    (existing.evidence, evidence),
                    key=lambda item: (item.final_rank, -item.hybrid_score),
                )
                collected[key] = ResearchEvidenceEntry(
                    evidence=best, task_ids=tuple(sorted({*existing.task_ids, result.task_id}))
                )
            else:
                evidence_to_chunk[source.evidence_id] = key
                collected[key] = ResearchEvidenceEntry(
                    evidence=evidence, task_ids=(result.task_id,)
                )
    ordered = sorted(
        collected.values(),
        key=lambda item: (
            item.evidence.final_rank,
            -item.evidence.hybrid_score,
            str(item.evidence.evidence.chunk_id),
        ),
    )
    accepted: list[ResearchEvidenceEntry] = []
    characters = 0
    for entry in ordered:
        size = len(entry.evidence.evidence.text.encode("utf-8"))
        if len(accepted) >= maximum_items or characters + size > maximum_characters:
            dropped += 1
            continue
        accepted.append(entry)
        characters += size
    return ResearchEvidenceLedger(
        entries=tuple(accepted), total_characters=characters, dropped_items=dropped
    )
