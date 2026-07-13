import pytest
from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.research.aggregation import aggregate_evidence
from enterprise_ai.retrieval.dense_retriever import DenseEvidence
from enterprise_ai.retrieval.evaluation import assessment_principal
from pydantic import ValidationError

from .evidence_fixtures import evidence, result


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("access_level", None),
        ("access_level", "unknown"),
        ("access_level", 42),
        ("allowed_roles", None),
        ("allowed_roles", ("unknown",)),
        ("allowed_roles", 42),
    ),
)
def test_malformed_authorization_metadata_fails_model_validation(field: str, value: object) -> None:
    values = evidence(1).evidence.model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        DenseEvidence.model_validate(values)


@pytest.mark.parametrize("field", ("access_level", "allowed_roles"))
def test_missing_authorization_metadata_fails_model_validation(field: str) -> None:
    values = evidence(1).evidence.model_dump()
    values.pop(field)
    with pytest.raises(ValidationError):
        DenseEvidence.model_validate(values)


@pytest.mark.parametrize(
    ("role", "level", "allowed", "accepted"),
    (
        (UserRole.VIEWER, AccessLevel.CONFIDENTIAL, frozenset({UserRole.ANALYST}), False),
        (UserRole.VIEWER, AccessLevel.RESTRICTED, frozenset({UserRole.ADMINISTRATOR}), False),
        (UserRole.ANALYST, AccessLevel.RESTRICTED, frozenset({UserRole.ADMINISTRATOR}), False),
        (UserRole.ADMINISTRATOR, AccessLevel.RESTRICTED, frozenset({UserRole.ADMINISTRATOR}), True),
        (UserRole.ADMINISTRATOR, AccessLevel.RESTRICTED, frozenset({UserRole.ANALYST}), False),
    ),
)
def test_ledger_revalidates_central_authorization(
    role: UserRole, level: AccessLevel, allowed: frozenset[UserRole], accepted: bool
) -> None:
    item = evidence(1, access_level=level, allowed_roles=allowed)
    ledger = aggregate_evidence(
        (result("T1", (item,)),),
        maximum_items=5,
        maximum_characters=100,
        principal=assessment_principal(role),
    )
    assert bool(ledger.entries) is accepted


def test_duplicate_authorization_mismatch_isolated() -> None:
    first = evidence(1)
    changed = evidence(1, allowed_roles=frozenset({UserRole.ADMINISTRATOR}))
    ledger = aggregate_evidence(
        (result("T1", (first,)), result("T2", (changed,))),
        maximum_items=5,
        maximum_characters=100,
    )
    assert len(ledger.entries) == 1 and ledger.dropped_items == 1
