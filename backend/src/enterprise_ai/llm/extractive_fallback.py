"""Deterministic, citation-preserving fallback synthesis from retrieved evidence."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from enterprise_ai.llm.models import EvidenceContextItem, GroundedAnswerDraft, GroundedClaim
from enterprise_ai.security.guardrails import (
    contains_untrusted_instruction,
    response_policy_violations,
)

_TOKEN = re.compile(r"[a-z0-9]+")
_PASSAGE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
_SPECIAL_CONCEPT_BOUNDARY = re.compile(
    r"\s*(?:;\s*|,\s*plus\s+|\bas\s+well\s+as\b|\bplus\b|\bversus\b|\bvs\.?\b)\s*",
    re.IGNORECASE,
)
_AND_BOUNDARY = re.compile(r"\s+\band\b\s+", re.IGNORECASE)
_QUESTION_CUE = re.compile(r"\b(?:for|about|regarding|covering)\b", re.IGNORECASE)
_HEADING = re.compile(r"^(?:#{1,6}\s*)?[A-Z][A-Z0-9 /&_-]{2,}:?$")
_OPERATIONAL_CUE = re.compile(
    r"\b(?:"
    r"before|after|when|if|until|unless|only|must|should|required|"
    r"stop|pause|halt|limit|bound|threshold|exceed|breach|worsen|"
    r"verify|validate|check|confirm|compare|reconcile|monitor|"
    r"rollback|quarantine|prevent|record|use|proceed|process|fail\s+over"
    r")\b",
    re.IGNORECASE,
)
_SUMMARY = "A degraded deterministic answer was extracted from authorized evidence."
_NO_SUPPORT = (
    "The authorized evidence did not contain enough detail to answer the request without guessing."
)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "both",
        "by",
        "can",
        "could",
        "describe",
        "do",
        "does",
        "explain",
        "for",
        "from",
        "give",
        "how",
        "i",
        "in",
        "include",
        "is",
        "it",
        "me",
        "of",
        "on",
        "or",
        "please",
        "provide",
        "should",
        "show",
        "summarize",
        "tell",
        "that",
        "the",
        "their",
        "this",
        "to",
        "use",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "would",
        "you",
    }
)
_SEMANTIC_GROUPS = (
    frozenset(
        {
            "control",
            "bound",
            "limit",
            "threshold",
            "pause",
            "stop",
            "halt",
            "rollback",
            "worsen",
            "health",
        }
    ),
    frozenset({"drain", "backlog", "queue", "batch", "process", "throughput", "work"}),
    frozenset(
        {
            "idempotency",
            "idempotent",
            "duplicate",
            "retry",
            "replay",
            "resubmit",
            "transaction",
        }
    ),
    frozenset(
        {
            "verification",
            "verify",
            "check",
            "validate",
            "confirm",
            "compare",
            "reconcile",
            "agreement",
            "audit",
            "test",
        }
    ),
)


@dataclass(frozen=True, slots=True)
class ExtractiveFallbackResult:
    """A safe fallback draft and bounded selection metadata."""

    draft: GroundedAnswerDraft
    selected_passage_count: int
    supported_concept_count: int
    requested_concept_count: int


@dataclass(frozen=True, slots=True)
class _Concept:
    label: str
    tokens: frozenset[str]
    expanded_tokens: frozenset[str]


@dataclass(frozen=True, slots=True)
class _Candidate:
    text: str
    evidence_id: str
    document_id: str
    evidence_rank: int
    passage_rank: int
    tokens: frozenset[str]
    operational_score: int


@dataclass(frozen=True, slots=True)
class _RankedCandidate:
    candidate: _Candidate
    score: tuple[int, int, int, int, int, int]


def build_extractive_fallback(
    question: str,
    contexts: Sequence[EvidenceContextItem],
    *,
    maximum_passages: int = 4,
    maximum_answer_characters: int = 4_000,
) -> ExtractiveFallbackResult:
    """Build a bounded answer from informative evidence passages only."""

    concepts = _question_concepts(question)
    question_tokens = _content_tokens(question)
    candidates = _candidates(contexts)
    ranked_by_concept = [
        _rank_candidates(
            candidates,
            concept=concept,
            question_tokens=question_tokens,
        )
        for concept in concepts
    ]
    selections = _select_complementary_passages(
        ranked_by_concept,
        maximum_passages=max(1, maximum_passages),
    )

    supported_indexes = {concept_index for concept_index, _candidate in selections}
    claims = tuple(
        GroundedClaim(
            claim_id=f"C{claim_index}",
            text=f"{concepts[concept_index].label}: {candidate.text}",
            supporting_evidence_ids=(candidate.evidence_id,),
        )
        for claim_index, (concept_index, candidate) in enumerate(selections, start=1)
    )
    claim_concepts = tuple(concept_index for concept_index, _candidate in selections)
    summary = _answer_summary(concepts, supported_indexes)

    while claims and _draft_length(summary, claims) > maximum_answer_characters:
        claims = claims[:-1]
        claim_concepts = claim_concepts[:-1]
        supported_indexes = set(claim_concepts)
        summary = _answer_summary(concepts, supported_indexes)

    if not claims:
        summary = _NO_SUPPORT

    draft = GroundedAnswerDraft(
        answer_summary=summary,
        claims=claims,
        insufficient_evidence=not claims,
    )
    return ExtractiveFallbackResult(
        draft=draft,
        selected_passage_count=len(claims),
        supported_concept_count=len(set(claim_concepts)),
        requested_concept_count=len(concepts),
    )


def _question_concepts(question: str) -> tuple[_Concept, ...]:
    cleaned = re.sub(r"\bboth\s+", "", question.strip(), flags=re.IGNORECASE)
    special_parts = [
        part.strip(" ,.?")
        for part in _SPECIAL_CONCEPT_BOUNDARY.split(cleaned)
        if part.strip(" ,.?")
    ]
    parts: list[str] = []
    for part in special_parts:
        parts.extend(_split_balanced_and(part))

    concepts: list[_Concept] = []
    seen_tokens: set[frozenset[str]] = set()
    for index, part in enumerate(parts):
        focused = _focus_concept_phrase(part)
        tokens = _content_tokens(focused)
        if not tokens or tokens in seen_tokens:
            continue
        seen_tokens.add(tokens)
        concepts.append(
            _Concept(
                label=_safe_concept_label(focused, index=index),
                tokens=tokens,
                expanded_tokens=_expand_semantics(tokens),
            )
        )

    if concepts:
        return tuple(concepts[:4])

    fallback_tokens = _content_tokens(question)
    if not fallback_tokens:
        fallback_tokens = frozenset({"request"})
    return (
        _Concept(
            label="requested information",
            tokens=fallback_tokens,
            expanded_tokens=_expand_semantics(fallback_tokens),
        ),
    )


def _split_balanced_and(value: str) -> list[str]:
    match = _AND_BOUNDARY.search(value)
    if match is None:
        return [value]

    left = value[: match.start()].strip(" ,.?")
    right = value[match.end() :].strip(" ,.?")
    if len(_content_tokens(left)) < 2 or len(_content_tokens(right)) < 2:
        return [value]
    return [*_split_balanced_and(left), *_split_balanced_and(right)]


def _focus_concept_phrase(value: str) -> str:
    matches = list(_QUESTION_CUE.finditer(value))
    if matches:
        tail = value[matches[-1].end() :].strip(" ,.?")
        if len(_content_tokens(tail)) >= 2:
            return tail
    return value.strip(" ,.?")


def _safe_concept_label(value: str, *, index: int) -> str:
    label = " ".join(value.split()).strip(" :;,.-")
    if (
        not label
        or len(label) > 80
        or contains_untrusted_instruction(label)
        or response_policy_violations(label)
    ):
        return f"requested aspect {index + 1}"
    return label[0].upper() + label[1:]


def _candidates(contexts: Sequence[EvidenceContextItem]) -> tuple[_Candidate, ...]:
    candidates: list[_Candidate] = []
    seen: set[tuple[str, str]] = set()
    for evidence_rank, context in enumerate(contexts):
        for passage_rank, passage in enumerate(_split_passages(context.text)):
            normalized = " ".join(passage.split()).strip(" -*")
            document_id = str(context.document_id)
            dedup_key = (normalized.casefold(), document_id)
            if (
                dedup_key in seen
                or len(normalized) < 24
                or len(normalized) > 700
                or _HEADING.fullmatch(normalized)
                or contains_untrusted_instruction(normalized)
                or response_policy_violations(normalized)
            ):
                continue
            tokens = _content_tokens(normalized)
            if not tokens:
                continue
            seen.add(dedup_key)
            candidates.append(
                _Candidate(
                    text=normalized,
                    evidence_id=context.model_id,
                    document_id=document_id,
                    evidence_rank=evidence_rank,
                    passage_rank=passage_rank,
                    tokens=tokens,
                    operational_score=len(_OPERATIONAL_CUE.findall(normalized)),
                )
            )
    return tuple(candidates)


def _split_passages(text: str) -> tuple[str, ...]:
    return tuple(part for part in _PASSAGE_BOUNDARY.split(text) if part.strip())


def _rank_candidates(
    candidates: Sequence[_Candidate],
    *,
    concept: _Concept,
    question_tokens: frozenset[str],
) -> tuple[_RankedCandidate, ...]:
    ranked: list[_RankedCandidate] = []
    for candidate in candidates:
        semantic_overlap = len(concept.expanded_tokens & candidate.tokens)
        direct_overlap = len(concept.tokens & candidate.tokens)
        novel_tokens = candidate.tokens - question_tokens
        novel_count = len(novel_tokens)
        novelty_ratio = int(100 * novel_count / max(1, len(candidate.tokens)))
        if semantic_overlap < 1 or novel_count < 1 or novelty_ratio < 30:
            continue
        if candidate.operational_score < 1 and not (semantic_overlap >= 2 and novel_count >= 2):
            continue

        score = (
            int(semantic_overlap >= 2),
            candidate.operational_score,
            semantic_overlap,
            min(novel_count, 12),
            novelty_ratio,
            direct_overlap,
        )
        ranked.append(_RankedCandidate(candidate=candidate, score=score))

    return tuple(
        sorted(
            ranked,
            key=lambda item: (
                tuple(-value for value in item.score),
                item.candidate.evidence_rank,
                item.candidate.passage_rank,
                item.candidate.text.casefold(),
            ),
        )
    )


def _select_complementary_passages(
    ranked_by_concept: Sequence[Sequence[_RankedCandidate]],
    *,
    maximum_passages: int,
) -> tuple[tuple[int, _Candidate], ...]:
    selected: list[tuple[int, _Candidate]] = []
    used_passages: set[tuple[str, str]] = set()
    concept_tokens: list[set[str]] = [set() for _ in ranked_by_concept]

    for selection_round in range(2):
        for concept_index, ranked in enumerate(ranked_by_concept):
            if len(selected) >= maximum_passages:
                return tuple(selected)
            for item in ranked:
                candidate = item.candidate
                passage_key = (candidate.text.casefold(), candidate.document_id)
                if passage_key in used_passages:
                    continue
                if selection_round and len(candidate.tokens - concept_tokens[concept_index]) < 2:
                    continue
                selected.append((concept_index, candidate))
                used_passages.add(passage_key)
                concept_tokens[concept_index].update(candidate.tokens)
                break
    return tuple(selected)


def _answer_summary(
    concepts: Sequence[_Concept],
    supported_indexes: set[int],
) -> str:
    if not supported_indexes:
        return _NO_SUPPORT
    unsupported = [
        concept.label for index, concept in enumerate(concepts) if index not in supported_indexes
    ]
    if not unsupported:
        return _SUMMARY
    return f"{_SUMMARY} The authorized evidence did not establish: {'; '.join(unsupported)}."


def _content_tokens(value: str) -> frozenset[str]:
    tokens = {
        normalized
        for raw in _TOKEN.findall(value.casefold())
        if (normalized := _normalize_token(raw)) not in _STOP_WORDS and len(normalized) > 1
    }
    return frozenset(tokens)


def _normalize_token(token: str) -> str:
    for prefix, normalized in (
        ("verif", "verify"),
        ("validat", "validate"),
        ("reconcil", "reconcile"),
        ("resubmit", "resubmit"),
        ("process", "process"),
        ("control", "control"),
        ("duplicat", "duplicate"),
        ("idempoten", "idempotency"),
    ):
        if token.startswith(prefix):
            return normalized
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _expand_semantics(tokens: frozenset[str]) -> frozenset[str]:
    expanded = set(tokens)
    for group in _SEMANTIC_GROUPS:
        if tokens & group:
            expanded.update(group)
    return frozenset(expanded)


def _draft_length(summary: str, claims: Sequence[GroundedClaim]) -> int:
    return len(summary) + sum(len(claim.text) for claim in claims)
