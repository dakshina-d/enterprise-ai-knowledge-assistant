"""Strict requests, rows, results, and provenance for structured analysis."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from enterprise_ai.models.common import ContractModel
from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.models.retrieval import DocumentType


class AnalysisOperation(StrEnum):
    COUNT_RECORDS = "count_records"
    GROUP_COUNT = "group_count"
    TOP_VALUES = "top_values"
    SEVERITY_DISTRIBUTION = "severity_distribution"
    STATUS_DISTRIBUTION = "status_distribution"
    DEPARTMENT_DISTRIBUTION = "department_distribution"
    DOCUMENT_TYPE_DISTRIBUTION = "document_type_distribution"
    DATE_HISTOGRAM = "date_histogram"
    DURATION_STATISTICS = "duration_statistics"
    RECURRING_ROOT_CAUSES = "recurring_root_causes"
    CORRECTIVE_ACTION_SUMMARY = "corrective_action_summary"
    COMPARE_GROUPS = "compare_groups"
    MISSING_VALUE_SUMMARY = "missing_value_summary"


class DateInterval(StrEnum):
    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class AnalysisFilters(ContractModel):
    document_ids: tuple[UUID, ...] = ()
    departments: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    root_cause_categories: tuple[str, ...] = ()
    affected_service: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def dates(self) -> Self:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date cannot follow end_date")
        return self


class AnalysisRequest(ContractModel):
    operation: AnalysisOperation
    filters: AnalysisFilters = Field(default_factory=AnalysisFilters)
    group_by: str | None = Field(default=None, max_length=100)
    field: str | None = Field(default=None, max_length=100)
    limit: Annotated[int, Field(ge=1, le=50)] = 10
    minimum_count: Annotated[int, Field(ge=1, le=1_000)] = 1
    interval: DateInterval = DateInterval.MONTH
    left_value: str | None = Field(default=None, max_length=200)
    right_value: str | None = Field(default=None, max_length=200)


class IncidentAnalysisRow(ContractModel):
    document_id: UUID
    incident_id: str | None
    title: str
    department: str
    document_type: DocumentType = DocumentType.INCIDENT
    access_level: AccessLevel
    allowed_roles: frozenset[UserRole]
    status: str
    created_date: date
    source_file: str
    severity: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_minutes: float | None = None
    affected_services: tuple[str, ...] = ()
    root_cause_category: str = "unknown"
    corrective_action_status: str | None = None


class AnalysisItem(ContractModel):
    key: str
    count: Annotated[int, Field(ge=0)]
    incident_ids: tuple[str, ...] = ()


class AnalysisProvenance(ContractModel):
    source_document_ids: tuple[UUID, ...]
    supporting_incident_ids: tuple[str, ...]
    formula: str
    taxonomy_version: str | None = None
    algorithm_version: str


class AnalysisResult(ContractModel):
    schema_version: str = "1.0"
    operation: AnalysisOperation
    status: str = "completed"
    row_count_considered: int
    row_count_excluded: int
    items: tuple[AnalysisItem, ...] = ()
    scalar_value: float | int | None = None
    statistics: dict[str, float] = Field(default_factory=dict)
    summary: str
    provenance: AnalysisProvenance
    warnings: tuple[str, ...] = ()
    request_id: UUID
    trace_id: UUID
