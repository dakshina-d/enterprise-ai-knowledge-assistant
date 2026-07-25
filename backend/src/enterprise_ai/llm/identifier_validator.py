"""Application-owned validation of enterprise identifiers in generated response text."""

import re
from dataclasses import dataclass

from enterprise_ai.llm.models import GroundedAnswerDraft, GroundedClaim

_INCIDENT_LIKE = re.compile(
    r"(?<![A-Z0-9])INC[-\s]+(?P<domain>[A-Z0-9]{2,12})[-\s]+"
    r"(?P<year>(?:19|20)\d{2})(?P<serial>(?:[-\s]+\d{1,6}){1,6})"
    r"(?![A-Z0-9-])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class IdentifierTextValidation:
    """A bounded repaired draft plus non-public validation findings."""

    draft: GroundedAnswerDraft
    errors: tuple[str, ...] = ()
    repair_count: int = 0


def validate_and_repair_response_identifiers(
    draft: GroundedAnswerDraft,
    requirements: tuple[tuple[str, tuple[str, ...]], ...],
) -> IdentifierTextValidation:
    """Preserve requested, evidence-backed identifiers in all publicly rendered draft text."""
    if not requirements:
        return IdentifierTextValidation(draft=draft)

    evidence_by_identifier = {
        identifier: frozenset(model_ids) for identifier, model_ids in requirements
    }
    supported = {
        identifier for identifier, model_ids in evidence_by_identifier.items() if model_ids
    }
    signatures = _allowed_signatures(supported)
    errors: list[str] = []
    repairs = 0

    summary, summary_identifiers, summary_errors, summary_repairs = _repair_text(
        draft.answer_summary,
        supported,
        signatures,
    )
    errors.extend(summary_errors)
    repairs += summary_repairs
    claims: list[GroundedClaim] = []

    for claim in draft.claims:
        text, claim_identifiers, claim_errors, claim_repairs = _repair_text(
            claim.text,
            supported,
            signatures,
        )
        errors.extend(claim_errors)
        repairs += claim_repairs
        claim_evidence = frozenset(claim.supporting_evidence_ids)
        aligned = {
            identifier
            for identifier, model_ids in evidence_by_identifier.items()
            if claim_evidence.intersection(model_ids)
        }
        if not set(claim_identifiers).issubset(aligned):
            errors.append("entity_identifier_validation_failed: claim identifier is off-target")
        claims.append(claim.model_copy(update={"text": text}))

    # Keep the authoritative scope at the start of the answer so final output
    # truncation cannot remove the only correct occurrence.
    missing = sorted(supported - set(summary_identifiers))
    if missing:
        prefix = (
            "Requested enterprise identifier"
            + ("s" if len(missing) > 1 else "")
            + ": "
            + ", ".join(missing)
            + "."
        )
        if len(prefix) + 1 + len(summary) <= 8_000:
            summary = f"{prefix} {summary}"
            repairs += len(missing)
        else:
            errors.append(
                "entity_identifier_validation_failed: supported requested identifier is absent"
            )

    repaired = draft.model_copy(
        update={
            "answer_summary": summary,
            "claims": tuple(claims),
        }
    )
    return IdentifierTextValidation(
        draft=repaired,
        errors=tuple(dict.fromkeys(errors)),
        repair_count=repairs,
    )


def _repair_text(
    text: str,
    allowed: set[str],
    signatures: dict[tuple[str, str, str], tuple[str, ...]],
) -> tuple[str, tuple[str, ...], tuple[str, ...], int]:
    identifiers: list[str] = []
    errors: list[str] = []
    repairs = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal repairs
        raw = match.group(0)
        canonical = _canonical_candidate(match)
        if raw in allowed:
            identifiers.append(raw)
            return raw
        if canonical in allowed:
            identifiers.append(canonical)
            repairs += 1
            return canonical
        candidates = signatures.get(_match_signature(match), ())
        if len(candidates) == 1:
            identifiers.append(candidates[0])
            repairs += 1
            return candidates[0]
        errors.append("entity_identifier_validation_failed: unapproved identifier-like token")
        return raw

    repaired = _INCIDENT_LIKE.sub(replace, text)
    return repaired, tuple(identifiers), tuple(errors), repairs


def _allowed_signatures(
    identifiers: set[str],
) -> dict[tuple[str, str, str], tuple[str, ...]]:
    collected: dict[tuple[str, str, str], list[str]] = {}
    for identifier in sorted(identifiers):
        match = _INCIDENT_LIKE.fullmatch(identifier)
        if match is None:
            continue
        collected.setdefault(_match_signature(match), []).append(identifier)
    return {key: tuple(values) for key, values in collected.items()}


def _canonical_candidate(match: re.Match[str]) -> str:
    serial_parts = re.findall(r"\d+", match.group("serial"))
    if len(serial_parts) != 1:
        return ""
    return f"INC-{match.group('domain').upper()}-{match.group('year')}-{serial_parts[0]}"


def _match_signature(match: re.Match[str]) -> tuple[str, str, str]:
    serial = "".join(re.findall(r"\d+", match.group("serial"))).lstrip("0") or "0"
    return match.group("domain").upper(), match.group("year"), serial
