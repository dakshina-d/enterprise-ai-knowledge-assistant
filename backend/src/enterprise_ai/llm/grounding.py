"""Deterministic bounded evidence context construction."""

from enterprise_ai.llm.models import EvidenceContextItem
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.security.guardrails import contains_untrusted_instruction


def build_evidence_context(
    evidence: tuple[HybridEvidence, ...], settings: RetrievalSettings
) -> tuple[EvidenceContextItem, ...]:
    result: list[EvidenceContextItem] = []
    remaining = settings.llm_max_evidence_characters
    ordered = sorted(
        evidence,
        key=lambda item: (item.final_rank, -item.hybrid_score, str(item.evidence.chunk_id)),
    )
    for index, item in enumerate(ordered[: settings.llm_max_evidence_items], start=1):
        source = item.evidence
        if contains_untrusted_instruction(source.text):
            continue
        if remaining <= 0:
            break
        text = source.text[: min(settings.llm_max_evidence_item_characters, remaining)]
        remaining -= len(text)
        result.append(
            EvidenceContextItem(
                model_id=f"E{index}",
                evidence_id=source.evidence_id,
                chunk_id=source.chunk_id,
                document_id=source.document_id,
                title=source.title,
                document_type=source.document_type.value,
                department=source.department,
                status=source.status,
                version=source.version,
                updated_date=source.updated_date.isoformat(),
                section=source.section,
                source_file=source.source_file,
                source_line_start=source.source_line_start,
                source_line_end=source.source_line_end,
                access_level=source.access_level.value,
                text=text,
                build_fingerprint=source.build_fingerprint,
            )
        )
    return tuple(result)
