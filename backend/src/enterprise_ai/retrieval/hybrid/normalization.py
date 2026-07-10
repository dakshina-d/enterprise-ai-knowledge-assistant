"""Deterministic per-branch min-max score normalization."""

import math
from collections.abc import Mapping

from enterprise_ai.retrieval.exceptions import RetrievalDataIntegrityError


def normalize_scores(scores: Mapping[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    if any(not math.isfinite(value) for value in scores.values()):
        raise RetrievalDataIntegrityError("retrieval score is non-finite")
    minimum, maximum = min(scores.values()), max(scores.values())
    if minimum == maximum:
        return {key: 1.0 for key in scores}
    return {key: (value - minimum) / (maximum - minimum) for key, value in scores.items()}
