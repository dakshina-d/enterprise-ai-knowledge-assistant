"""Small typed Okapi BM25 implementation."""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    chunk_id: str
    score: float


def score_corpus(
    query_tokens: Sequence[str],
    documents: Mapping[str, tuple[int, Mapping[str, int]]],
    document_frequencies: Mapping[str, int],
    average_length: float,
    *,
    k1: float,
    b: float,
) -> tuple[ScoredChunk, ...]:
    if not query_tokens:
        raise ValueError("BM25 query is empty")
    if not documents or average_length <= 0 or k1 <= 0 or not 0 <= b <= 1:
        raise ValueError("BM25 corpus or parameters are invalid")
    query_counts = Counter(query_tokens)
    total = len(documents)
    results: list[ScoredChunk] = []
    for chunk_id, (length, frequencies) in documents.items():
        score = 0.0
        for term, query_frequency in query_counts.items():
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            document_frequency = document_frequencies.get(term, 0)
            inverse_document_frequency = math.log(
                1 + (total - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            denominator = frequency + k1 * (1 - b + b * length / average_length)
            score += (
                query_frequency * inverse_document_frequency * frequency * (k1 + 1) / denominator
            )
        if score > 0 and math.isfinite(score):
            results.append(ScoredChunk(chunk_id, score))
    return tuple(sorted(results, key=lambda item: (-item.score, item.chunk_id)))
