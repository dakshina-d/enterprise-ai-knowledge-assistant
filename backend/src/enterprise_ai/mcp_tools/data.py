"""Deterministic fictional enterprise service dataset with no personal data."""

from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType

from enterprise_ai.mcp_tools.models import (
    SNAPSHOT_TIME,
    BusinessCriticality,
    ChangeStatus,
    ChangeWindow,
    LifecycleStatus,
    MetricPeriod,
    OperationalMetrics,
    ServiceProfile,
    ServiceRecord,
    ServiceTier,
    normalize_service_name,
)

FICTIONAL_DATA_NOTICE = "All records are fictional enterprise demonstration data."

_SERVICE_ROWS = (
    ("payment-gateway", "Payments Platform", "Digital Payments", ServiceTier.TIER_1, 99.98, 142),
    (
        "card-settlement",
        "Settlement Systems",
        "Payments Operations",
        ServiceTier.TIER_1,
        99.95,
        188,
    ),
    ("mobile-banking-api", "Mobile Experience", "Digital Channels", ServiceTier.TIER_1, 99.97, 126),
    (
        "customer-notification",
        "Customer Messaging",
        "Customer Experience",
        ServiceTier.TIER_2,
        99.91,
        215,
    ),
    ("identity-access", "Identity Platform", "Cybersecurity", ServiceTier.TIER_1, 99.99, 84),
    ("fraud-screening", "Fraud Technology", "Risk", ServiceTier.TIER_1, 99.96, 164),
    (
        "customer-profile",
        "Customer Data Platform",
        "Customer Experience",
        ServiceTier.TIER_2,
        99.93,
        201,
    ),
)


def _record(
    index: int,
    name: str,
    team: str,
    department: str,
    tier: ServiceTier,
    availability: float,
    latency: int,
) -> ServiceRecord:
    profile = ServiceProfile(
        service_name=name,
        owning_team=team,
        department=department,
        tier=tier,
        criticality=(
            BusinessCriticality.CRITICAL if tier is ServiceTier.TIER_1 else BusinessCriticality.HIGH
        ),
        support_hours="24x7" if tier is ServiceTier.TIER_1 else "06:00-22:00 UTC daily",
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    metrics = tuple(
        OperationalMetrics(
            service_name=name,
            period=period,
            availability_percentage=round(availability - offset * 0.01, 2),
            request_count=(index + 2) * multiplier,
            error_rate_percentage=round(100 - availability + offset * 0.01, 2),
            p95_latency_ms=latency + offset * 9,
            active_incidents=index % 2,
            snapshot_timestamp=SNAPSHOT_TIME,
        )
        for period, multiplier, offset in (
            (MetricPeriod.CURRENT, 13_000, 0),
            (MetricPeriod.HOURS_24, 260_000, 1),
            (MetricPeriod.DAYS_7, 1_820_000, 2),
        )
    )
    start = datetime(2026, 7, 25 + index, 1, 0, tzinfo=UTC)
    changes = (
        ChangeWindow(
            change_id=f"CHG-{2100 + index}",
            change_type="Routine platform maintenance",
            start_time=start,
            end_time=start + timedelta(hours=2),
            status=ChangeStatus.APPROVED if index % 2 == 0 else ChangeStatus.PLANNED,
            affected_service=name,
            owning_team=team,
        ),
    )
    return ServiceRecord(
        profile=profile,
        last_deployment_date=date(2026, 7, 10 + index),
        metrics=metrics,
        change_windows=changes,
    )


_RECORDS = tuple(_record(index, *row) for index, row in enumerate(_SERVICE_ROWS))
if len({record.profile.service_name for record in _RECORDS}) != len(_RECORDS):
    raise RuntimeError("fictional MCP dataset contains duplicate service names")

SERVICE_CATALOG = MappingProxyType({record.profile.service_name: record for record in _RECORDS})
SERVICE_NAMES = tuple(SERVICE_CATALOG)


def get_record(service_name: str) -> ServiceRecord:
    """Return one exact canonical record without fuzzy matching."""
    normalized = normalize_service_name(service_name)
    try:
        return SERVICE_CATALOG[normalized]
    except KeyError as error:
        raise ValueError("unknown service") from error
