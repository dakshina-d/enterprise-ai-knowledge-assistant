"""Deterministic lexical relevance rules for authorized sparse candidates."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

INSTRUCTION_TERMS = frozenset(
    {
        "describe",
        "explain",
        "find",
        "give",
        "identify",
        "list",
        "outline",
        "please",
        "provide",
        "retrieve",
        "show",
        "summarize",
        "tell",
    }
)
STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "all",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)
# These terms describe corpus containers rather than the requested subject.
GENERIC_CORPUS_TERMS = frozenset(
    {
        "active",
        "approved",
        "bank",
        "control",
        "controls",
        "current",
        "data",
        "document",
        "documents",
        "enterprise",
        "information",
        "policy",
        "policies",
        "procedure",
        "procedures",
        "source",
        "sources",
    }
)


def salient_query_terms(tokens: Sequence[str]) -> tuple[str, ...]:
    """Return stable meaningful terms, excluding request verbs and corpus-generic words."""
    excluded = INSTRUCTION_TERMS | STOP_WORDS | GENERIC_CORPUS_TERMS
    return tuple(dict.fromkeys(term for term in tokens if len(term) > 1 and term not in excluded))


def matched_salient_terms(
    salient_terms: Sequence[str], frequencies: Mapping[str, int]
) -> tuple[str, ...]:
    return tuple(term for term in salient_terms if frequencies.get(term, 0) > 0)


def has_adequate_support(salient_terms: Sequence[str], matched_terms: Sequence[str]) -> bool:
    """Require all short-query concepts or at least half of a longer query's concepts."""
    if not salient_terms:
        return False
    required = (
        len(salient_terms) if len(salient_terms) <= 2 else math.ceil(len(salient_terms) * 0.5)
    )
    return len(matched_terms) >= required
