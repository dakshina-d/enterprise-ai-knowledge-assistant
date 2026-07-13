"""Typed deterministic conflict detection for bounded structured facts."""

from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from enterprise_ai.models.common import ContractModel
from enterprise_ai.models.identity import AccessLevel, AuthenticatedPrincipal, UserRole
from enterprise_ai.models.retrieval import DocumentMetadata, DocumentType
from enterprise_ai.security.authorization import AuthorizationService


class StructuredFactType(StrEnum):
    INCIDENT_START_TIME = "incident_start_time"
    INCIDENT_END_TIME = "incident_end_time"
    INCIDENT_RECOVERY_TIME = "incident_recovery_time"
    INCIDENT_DURATION_MINUTES = "incident_duration_minutes"
    POLICY_EFFECTIVE_DATE = "policy_effective_date"
    POLICY_APPROVAL_DATE = "policy_approval_date"
    DOCUMENT_UPDATED_DATE = "document_updated_date"
    SERVICE_OWNER = "service_owner"
    DOCUMENT_OWNER = "document_owner"
    RESPONSIBLE_DEPARTMENT = "responsible_department"
    OPERATIONAL_TEAM = "operational_team"
    COMPONENT_SERVICE_MAPPING = "component_service_mapping"
    SERVICE_DEPARTMENT_MAPPING = "service_department_mapping"


class StructuredConflictKind(StrEnum):
    VALUE_MISMATCH = "value_mismatch"


class StructuredFact(ContractModel):
    fact_type: StructuredFactType
    subject: Annotated[str, Field(min_length=1, max_length=200)]
    value: Annotated[str, Field(min_length=1, max_length=500)]
    evidence_id: UUID
    chunk_id: UUID
    document_id: UUID
    document_title: str
    document_type: DocumentType
    status: str
    version: str
    updated_date: date
    access_level: AccessLevel
    allowed_roles: frozenset[UserRole]
    source_file: str
    source_line_start: int = Field(ge=1)
    source_line_end: int = Field(ge=1)
    task_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def normalize_and_validate(self) -> Self:
        if self.source_line_end < self.source_line_start:
            raise ValueError("source line range is invalid")
        object.__setattr__(self, "value", normalize_value(self.fact_type, self.value))
        return self


class StructuredConflict(ContractModel):
    conflict_id: str
    kind: StructuredConflictKind
    fact_type: StructuredFactType
    subject: str
    preferred_fact: StructuredFact
    conflicting_facts: tuple[StructuredFact, ...]
    authority_rationale_code: str
    affected_task_ids: tuple[str, ...]
    material: bool = True
    resolution_status: str = "unresolved"
    warning: str = "Authorized structured sources disagree."


def normalize_value(kind: StructuredFactType, value: str) -> str:
    if kind in {
        StructuredFactType.INCIDENT_START_TIME,
        StructuredFactType.INCIDENT_END_TIME,
        StructuredFactType.INCIDENT_RECOVERY_TIME,
    }:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("structured datetime must include a timezone")
        return parsed.astimezone(UTC).isoformat()
    if kind in {
        StructuredFactType.POLICY_EFFECTIVE_DATE,
        StructuredFactType.POLICY_APPROVAL_DATE,
        StructuredFactType.DOCUMENT_UPDATED_DATE,
    }:
        return date.fromisoformat(value).isoformat()
    if kind is StructuredFactType.INCIDENT_DURATION_MINUTES:
        duration = float(value)
        if duration < 0 or not duration < float("inf"):
            raise ValueError("duration must be finite and non-negative")
        return format(duration, ".12g")
    return " ".join(value.casefold().split())


def validate_incident_range(start: StructuredFact, end: StructuredFact) -> None:
    if (
        start.fact_type is not StructuredFactType.INCIDENT_START_TIME
        or end.fact_type is not StructuredFactType.INCIDENT_END_TIME
    ):
        raise ValueError("incident range facts are invalid")
    if datetime.fromisoformat(end.value) < datetime.fromisoformat(start.value):
        raise ValueError("incident end precedes start")


def detect_structured_conflicts(
    facts: tuple[StructuredFact, ...],
    principal: AuthenticatedPrincipal,
    authorization: AuthorizationService | None = None,
) -> tuple[StructuredConflict, ...]:
    policy = authorization or AuthorizationService()
    authorized = []
    for fact in facts:
        metadata = DocumentMetadata(
            document_id=fact.document_id,
            title=fact.document_title,
            source="structured_fact",
            department="structured",
            document_type=fact.document_type,
            access_level=fact.access_level,
            allowed_roles=fact.allowed_roles,
            created_date=fact.updated_date,
            updated_date=fact.updated_date,
            version=fact.version,
            content_hash="0" * 64,
        )
        if policy.is_document_authorized(principal, metadata):
            authorized.append(fact)
    groups: dict[tuple[StructuredFactType, str], list[StructuredFact]] = {}
    for fact in authorized:
        groups.setdefault((fact.fact_type, fact.subject.casefold()), []).append(fact)
    output = []
    for (kind, subject), items in groups.items():
        if len({item.value for item in items}) < 2:
            continue
        ordered = sorted(items, key=_authority_key)
        digest = sha256(
            (
                kind.value
                + "|"
                + subject
                + "|"
                + "|".join(sorted(str(item.evidence_id) for item in items))
            ).encode()
        ).hexdigest()[:16]
        output.append(
            StructuredConflict(
                conflict_id=f"SC-{digest}",
                kind=StructuredConflictKind.VALUE_MISMATCH,
                fact_type=kind,
                subject=subject,
                preferred_fact=ordered[0],
                conflicting_facts=tuple(ordered[1:]),
                authority_rationale_code="status_authority_then_date",
                affected_task_ids=tuple(sorted({task for item in items for task in item.task_ids})),
            )
        )
    return tuple(sorted(output, key=lambda item: item.conflict_id))


def _authority_key(fact: StructuredFact) -> tuple[int, int, str]:
    rank = {"approved": 0, "active": 1, "final": 2, "draft": 8, "superseded": 9, "retired": 10}
    return (
        rank.get(fact.status.casefold(), 5),
        -fact.updated_date.toordinal(),
        str(fact.evidence_id),
    )
