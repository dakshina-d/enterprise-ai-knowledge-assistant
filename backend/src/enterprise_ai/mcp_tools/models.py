"""Strict application-owned models for fictional enterprise MCP data."""

import re
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from enterprise_ai.models.common import ContractModel
from enterprise_ai.models.validation import ensure_utc_aware

SERVER_NAME = "enterprise-fictional-data"
PROTOCOL_VERSION = "2025-11-25"
TRANSPORT_TYPE = "in-memory"
TOOL_NAMES = (
    "get_service_profile",
    "get_operational_metrics",
    "get_change_windows",
)
SERVICE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
UNSAFE_TEXT = re.compile(r"[\x00-\x1f\x7f]|(?:\.\.)|[\\/:*?\"<>|$`(){}\[\];&]")


def normalize_service_name(value: str) -> str:
    """Normalize a bounded canonical service selector and reject instruction-like input."""
    normalized = value.strip().casefold()
    if not normalized or len(normalized) > 80:
        raise ValueError("service name is invalid")
    if UNSAFE_TEXT.search(normalized) or not SERVICE_PATTERN.fullmatch(normalized):
        raise ValueError("service name is invalid")
    return normalized


class ServiceTier(StrEnum):
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class BusinessCriticality(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"


class LifecycleStatus(StrEnum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    RETIRING = "retiring"


class ChangeStatus(StrEnum):
    PLANNED = "planned"
    APPROVED = "approved"
    COMPLETED = "completed"


class MetricPeriod(StrEnum):
    CURRENT = "current"
    HOURS_24 = "24h"
    DAYS_7 = "7d"


class ServiceProfile(ContractModel):
    result_type: Literal["service_profile"] = "service_profile"
    service_name: Annotated[str, Field(min_length=1, max_length=80)]
    owning_team: Annotated[str, Field(min_length=1, max_length=100)]
    department: Annotated[str, Field(min_length=1, max_length=100)]
    tier: ServiceTier
    criticality: BusinessCriticality
    support_hours: Annotated[str, Field(min_length=1, max_length=80)]
    lifecycle_status: LifecycleStatus

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, value: str) -> str:
        return normalize_service_name(value)


class OperationalMetrics(ContractModel):
    result_type: Literal["operational_metrics"] = "operational_metrics"
    service_name: Annotated[str, Field(min_length=1, max_length=80)]
    period: MetricPeriod
    availability_percentage: Annotated[float, Field(ge=0, le=100)]
    request_count: Annotated[int, Field(ge=0, le=1_000_000_000)]
    error_rate_percentage: Annotated[float, Field(ge=0, le=100)]
    p95_latency_ms: Annotated[int, Field(ge=0, le=3_600_000)]
    active_incidents: Annotated[int, Field(ge=0, le=10_000)]
    snapshot_timestamp: datetime

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, value: str) -> str:
        return normalize_service_name(value)

    @field_validator("snapshot_timestamp")
    @classmethod
    def validate_snapshot(cls, value: datetime) -> datetime:
        return ensure_utc_aware(value)


class ChangeWindow(ContractModel):
    change_id: Annotated[str, Field(pattern=r"^CHG-[0-9]{4}$")]
    change_type: Annotated[str, Field(min_length=1, max_length=100)]
    start_time: datetime
    end_time: datetime
    status: ChangeStatus
    affected_service: Annotated[str, Field(min_length=1, max_length=80)]
    owning_team: Annotated[str, Field(min_length=1, max_length=100)]

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return ensure_utc_aware(value)

    @field_validator("affected_service")
    @classmethod
    def validate_service_name(cls, value: str) -> str:
        return normalize_service_name(value)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("change window must end after it starts")
        return self


class ChangeWindowResult(ContractModel):
    result_type: Literal["change_windows"] = "change_windows"
    service_name: Annotated[str, Field(min_length=1, max_length=80)]
    windows: tuple[ChangeWindow, ...] = ()

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, value: str) -> str:
        return normalize_service_name(value)


type MCPToolResult = ServiceProfile | OperationalMetrics | ChangeWindowResult


class ServiceRecord(ContractModel):
    profile: ServiceProfile
    last_deployment_date: date
    metrics: tuple[OperationalMetrics, ...]
    change_windows: tuple[ChangeWindow, ...]

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if {item.period for item in self.metrics} != set(MetricPeriod):
            raise ValueError("every metrics period must be present exactly once")
        if any(item.service_name != self.profile.service_name for item in self.metrics):
            raise ValueError("metrics service does not match profile")
        if any(item.affected_service != self.profile.service_name for item in self.change_windows):
            raise ValueError("change service does not match profile")
        return self


class GetServiceProfileArguments(ContractModel):
    service_name: Annotated[str, Field(min_length=1, max_length=80)]

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, value: str) -> str:
        return normalize_service_name(value)


class GetOperationalMetricsArguments(GetServiceProfileArguments):
    period: MetricPeriod = MetricPeriod.HOURS_24


class GetChangeWindowsArguments(GetServiceProfileArguments):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValueError("end date must not precede start date")
            if self.end_date - self.start_date > timedelta(days=90):
                raise ValueError("date range exceeds 90 days")
        return self


class MCPProvenance(ContractModel):
    source_type: Literal["mcp_tool"] = "mcp_tool"
    server_name: Literal["enterprise-fictional-data"] = "enterprise-fictional-data"
    tool_name: Literal[
        "get_service_profile",
        "get_operational_metrics",
        "get_change_windows",
    ]
    record_identifier: Annotated[str, Field(min_length=1, max_length=80)]
    snapshot_timestamp: datetime | None = None


class MCPExecutionResult(ContractModel):
    tool_name: Literal[
        "get_service_profile",
        "get_operational_metrics",
        "get_change_windows",
    ]
    status: Literal["completed"] = "completed"
    result: MCPToolResult
    provenance: MCPProvenance
    response_text: Annotated[str, Field(min_length=1, max_length=4_000)]


class SelectedMCPTool(ContractModel):
    tool_name: Literal[
        "get_service_profile",
        "get_operational_metrics",
        "get_change_windows",
    ]
    service_name: Annotated[str, Field(min_length=1, max_length=80)]
    period: MetricPeriod | None = None
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, value: str) -> str:
        return normalize_service_name(value)


SNAPSHOT_TIME = datetime(2026, 7, 20, 6, 0, tzinfo=UTC)
