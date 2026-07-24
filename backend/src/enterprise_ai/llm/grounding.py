"""Deterministic bounded evidence context construction."""

from enterprise_ai.llm.models import EvidenceContextItem
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.security.guardrails import contains_untrusted_instruction


def build_evidence_context(
    evidence: tuple[HybridEvidence, ...],
    settings: RetrievalSettings,
    *,
    maximum_items: int | None = None,
) -> tuple[EvidenceContextItem, ...]:
    result: list[EvidenceContextItem] = []
    remaining = settings.llm_max_evidence_characters
    ordered = sorted(
        evidence,
        key=lambda item: (item.final_rank, -item.hybrid_score, str(item.evidence.chunk_id)),
    )
    item_limit = settings.llm_max_evidence_items if maximum_items is None else maximum_items
    item_limit = min(item_limit, settings.research_max_evidence_items, settings.llm_max_citations)
    selected = ordered[:item_limit]
    per_item_budget = (
        max(1, settings.llm_max_evidence_characters // len(selected))
        if maximum_items is not None and selected
        else settings.llm_max_evidence_item_characters
    )
    for index, item in enumerate(selected, start=1):
        source = item.evidence
        if contains_untrusted_instruction(source.text):
            continue
        if remaining <= 0:
            break
        text_budget = min(settings.llm_max_evidence_item_characters, per_item_budget, remaining)
        text = _bounded_excerpt(
            source.text,
            text_budget,
            preserve_ends=maximum_items is not None,
        )
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


def _bounded_excerpt(text: str, maximum_characters: int, *, preserve_ends: bool) -> str:
    if len(text) <= maximum_characters:
        return text
    if not preserve_ends or maximum_characters < 20:
        return text[:maximum_characters]
    separator = "\n...\n"
    available = maximum_characters - len(separator)
    prefix = (available + 1) // 2
    suffix = available - prefix
    return text[:prefix] + separator + text[-suffix:]
