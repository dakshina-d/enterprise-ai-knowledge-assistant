from datetime import date
from uuid import UUID

import pytest
from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.models.retrieval import DocumentType
from enterprise_ai.research.structured_conflicts import (
    StructuredFact,
    StructuredFactType,
    detect_structured_conflicts,
    validate_incident_range,
)
from enterprise_ai.retrieval.evaluation import assessment_principal


def _fact(
    identifier: int, kind: StructuredFactType, value: str, **changes: object
) -> StructuredFact:
    return StructuredFact(
        fact_type=kind,
        subject="HorizonPay",
        value=value,
        evidence_id=UUID(int=identifier),
        chunk_id=UUID(int=identifier),
        document_id=UUID(int=identifier),
        document_title="Safe",
        document_type=DocumentType.INCIDENT,
        status="active",
        version="1",
        updated_date=date(2026, 1, 1),
        access_level=AccessLevel.INTERNAL,
        allowed_roles=frozenset({UserRole.VIEWER}),
        source_file="safe.md",
        source_line_start=1,
        source_line_end=2,
        task_ids=(f"T{identifier}",),
    ).model_copy(update=changes)


def test_equivalent_timezone_instants_do_not_conflict() -> None:
    facts = (
        _fact(1, StructuredFactType.INCIDENT_START_TIME, "2026-01-01T00:00:00Z"),
        _fact(2, StructuredFactType.INCIDENT_START_TIME, "2026-01-01T05:30:00+05:30"),
    )
    assert not detect_structured_conflicts(facts, assessment_principal(UserRole.VIEWER))


@pytest.mark.parametrize("value", ("2026-01-01T00:00:00", "not-a-time"))
def test_naive_or_malformed_timestamp_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        _fact(1, StructuredFactType.INCIDENT_START_TIME, value)


def test_end_before_start_is_rejected() -> None:
    start = _fact(1, StructuredFactType.INCIDENT_START_TIME, "2026-01-02T00:00:00Z")
    end = _fact(2, StructuredFactType.INCIDENT_END_TIME, "2026-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        validate_incident_range(start, end)


@pytest.mark.parametrize(
    "kind",
    (
        StructuredFactType.INCIDENT_START_TIME,
        StructuredFactType.INCIDENT_END_TIME,
        StructuredFactType.INCIDENT_RECOVERY_TIME,
        StructuredFactType.POLICY_EFFECTIVE_DATE,
        StructuredFactType.POLICY_APPROVAL_DATE,
        StructuredFactType.SERVICE_OWNER,
        StructuredFactType.RESPONSIBLE_DEPARTMENT,
        StructuredFactType.OPERATIONAL_TEAM,
        StructuredFactType.COMPONENT_SERVICE_MAPPING,
        StructuredFactType.SERVICE_DEPARTMENT_MAPPING,
    ),
)
def test_material_authorized_values_create_deterministic_conflict(kind: StructuredFactType) -> None:
    values = (
        "2026-01-01"
        if "date" in kind.value
        else "2026-01-01T00:00:00Z"
        if "time" in kind.value
        else "alpha",
        "2026-02-01"
        if "date" in kind.value
        else "2026-01-02T00:00:00Z"
        if "time" in kind.value
        else "beta",
    )
    facts = (
        _fact(1, kind, values[0], status="approved"),
        _fact(2, kind, values[1], status="draft"),
    )
    conflicts = detect_structured_conflicts(facts, assessment_principal(UserRole.VIEWER))
    assert conflicts == detect_structured_conflicts(
        tuple(reversed(facts)), assessment_principal(UserRole.VIEWER)
    )
    assert conflicts[0].preferred_fact.evidence_id == UUID(int=1)


def test_unauthorized_fact_cannot_create_visible_conflict() -> None:
    allowed = _fact(1, StructuredFactType.SERVICE_OWNER, "owner-a")
    denied = _fact(
        2,
        StructuredFactType.SERVICE_OWNER,
        "owner-b",
        access_level=AccessLevel.RESTRICTED,
        allowed_roles=frozenset({UserRole.ADMINISTRATOR}),
        document_title="hidden",
    )
    assert not detect_structured_conflicts((allowed, denied), assessment_principal(UserRole.VIEWER))
