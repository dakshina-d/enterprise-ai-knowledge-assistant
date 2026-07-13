import math

import pytest
from enterprise_ai.retrieval.dense_retriever import DenseEvidence
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from pydantic import ValidationError

from .evidence_fixtures import evidence


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_dense_non_finite_scores_are_rejected(value: float) -> None:
    values = evidence(1).evidence.model_dump()
    values["dense_score"] = value
    with pytest.raises(ValidationError):
        DenseEvidence.model_validate(values)


@pytest.mark.parametrize("value", (-1.0, 0.0, 0.75))
def test_dense_finite_scores_are_allowed(value: float) -> None:
    assert evidence(1, dense_score=value).evidence.dense_score == value


@pytest.mark.parametrize("field", ("raw_dense_score", "raw_sparse_score", "hybrid_score"))
@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_hybrid_non_finite_scores_are_rejected(field: str, value: float) -> None:
    values = evidence(1).model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        HybridEvidence.model_validate(values)


@pytest.mark.parametrize("value", (-0.1, 1.1))
def test_hybrid_normalized_range_is_enforced(value: float) -> None:
    values = evidence(1).model_dump()
    values["hybrid_score"] = value
    with pytest.raises(ValidationError):
        HybridEvidence.model_validate(values)


@pytest.mark.parametrize("value", (0.0, 0.5, 1.0))
def test_hybrid_valid_range_is_allowed(value: float) -> None:
    assert evidence(1).model_copy(update={"hybrid_score": value}).hybrid_score == value
