"""Bounded extraction and corpus resolution for recognized enterprise identifiers."""

import re
from enum import StrEnum
from uuid import UUID

from enterprise_ai_ingestion.models import ChunkRecord
from pydantic import Field

from enterprise_ai.models.common import ContractModel

MAX_ENTERPRISE_IDENTIFIERS = 4
MAX_ENTERPRISE_IDENTIFIER_CHARACTERS = 64
_INCIDENT = re.compile(
    r"(?<![A-Z0-9])INC-[A-Z0-9]{2,12}-(?:19|20)\d{2}-\d{3,6}(?![A-Z0-9-])",
    re.IGNORECASE,
)


class EnterpriseIdentifierKind(StrEnum):
    INCIDENT = "incident"


class EnterpriseIdentifier(ContractModel):
    normalized: str = Field(min_length=1, max_length=MAX_ENTERPRISE_IDENTIFIER_CHARACTERS)
    original: str = Field(min_length=1, max_length=MAX_ENTERPRISE_IDENTIFIER_CHARACTERS)
    kind: EnterpriseIdentifierKind


def extract_enterprise_identifiers(text: str) -> tuple[EnterpriseIdentifier, ...]:
    """Extract a small recognized set without evaluating user-controlled regular expressions."""
    found: list[EnterpriseIdentifier] = []
    seen: set[str] = set()
    for match in _INCIDENT.finditer(text[:4_000]):
        original = match.group(0)
        normalized = original.upper()
        if normalized in seen:
            continue
        seen.add(normalized)
        found.append(
            EnterpriseIdentifier(
                normalized=normalized,
                original=original,
                kind=EnterpriseIdentifierKind.INCIDENT,
            )
        )
        if len(found) >= MAX_ENTERPRISE_IDENTIFIERS:
            break
    return tuple(found)


def identifier_document_ids(
    chunks: tuple[ChunkRecord, ...],
    identifiers: tuple[EnterpriseIdentifier, ...],
) -> dict[str, frozenset[UUID]]:
    """Resolve identifiers across every chunk so chunk boundaries cannot weaken exact matching."""
    requested = {item.normalized for item in identifiers}
    matches: dict[str, set[UUID]] = {item: set() for item in requested}
    if not requested:
        return {}
    for chunk in chunks:
        present = {
            item.normalized
            for item in extract_enterprise_identifiers(chunk.search_text)
            if item.normalized in requested
        }
        for identifier in present:
            matches[identifier].add(chunk.document_id)
    return {key: frozenset(value) for key, value in matches.items()}


def matching_document_ids(
    chunks: tuple[ChunkRecord, ...],
    identifiers: tuple[EnterpriseIdentifier, ...],
) -> frozenset[UUID]:
    by_identifier = identifier_document_ids(chunks, identifiers)
    return frozenset(
        document_id for document_ids in by_identifier.values() for document_id in document_ids
    )
