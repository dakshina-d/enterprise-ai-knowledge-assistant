"""Pure bounded trusted-Python aggregate operations."""

import statistics
from collections import Counter, defaultdict
from datetime import date
from uuid import UUID

from enterprise_ai.tools.python_analysis import ALGORITHM_VERSION, TAXONOMY_VERSION
from enterprise_ai.tools.python_analysis.exceptions import (
    AnalysisLimitError,
    AnalysisValidationError,
)
from enterprise_ai.tools.python_analysis.models import (
    AnalysisFilters,
    AnalysisItem,
    AnalysisOperation,
    AnalysisProvenance,
    AnalysisRequest,
    AnalysisResult,
    IncidentAnalysisRow,
)

_FIELDS = {
    "department": lambda row: row.department,
    "document_type": lambda row: row.document_type.value,
    "severity": lambda row: row.severity,
    "status": lambda row: row.status,
    "root_cause_category": lambda row: row.root_cause_category,
    "corrective_action_status": lambda row: row.corrective_action_status,
}


def _filter(
    rows: tuple[IncidentAnalysisRow, ...], filters: AnalysisFilters
) -> tuple[IncidentAnalysisRow, ...]:
    return tuple(
        row
        for row in rows
        if (
            (not filters.document_ids or row.document_id in filters.document_ids)
            and (not filters.departments or row.department in filters.departments)
            and (not filters.statuses or row.status in filters.statuses)
            and (not filters.severities or row.severity in filters.severities)
            and (
                not filters.root_cause_categories
                or row.root_cause_category in filters.root_cause_categories
            )
            and (not filters.affected_service or filters.affected_service in row.affected_services)
            and (
                not filters.start_date
                or (row.start_time and row.start_time.date() >= filters.start_date)
            )
            and (not filters.end_date or (row.end_time and row.end_time.date() <= filters.end_date))
        )
    )


def execute_analysis(
    request: AnalysisRequest,
    rows: tuple[IncidentAnalysisRow, ...],
    *,
    request_id: UUID,
    trace_id: UUID,
    maximum_groups: int,
    maximum_distinct: int,
) -> AnalysisResult:
    selected = _filter(rows, request.filters)
    operation = request.operation
    items: tuple[AnalysisItem, ...] = ()
    scalar: float | int | None = None
    stats: dict[str, float] = {}
    formula = "authorized rows after typed narrowing filters"
    if operation is AnalysisOperation.COUNT_RECORDS:
        scalar = len(selected)
    elif operation is AnalysisOperation.DURATION_STATISTICS:
        values = [row.duration_minutes for row in selected if row.duration_minutes is not None]
        if values:
            stats = {
                "minimum": min(values),
                "maximum": max(values),
                "mean": statistics.fmean(values),
                "median": statistics.median(values),
            }
        formula = "standard-library min, max, arithmetic mean, and median over valid durations"
    elif operation is AnalysisOperation.DATE_HISTOGRAM:
        counter: Counter[str] = Counter()
        for row in selected:
            value = row.start_time.date() if row.start_time else row.created_date
            key = _date_key(value, request.interval.value)
            counter[key] += 1
        items = _counter_items(
            counter,
            selected,
            lambda row: _date_key(
                row.start_time.date() if row.start_time else row.created_date,
                request.interval.value,
            ),
            request.limit,
        )
    else:
        field = _operation_field(operation, request)
        accessor = _FIELDS.get(field)
        if accessor is None:
            raise AnalysisValidationError("analysis field is not supported")
        grouped: defaultdict[str, list[IncidentAnalysisRow]] = defaultdict(list)
        for row in selected:
            grouped[str(accessor(row) or "missing")].append(row)
        if len(grouped) > maximum_distinct:
            raise AnalysisLimitError("distinct-value limit exceeded")
        ordered = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        items = tuple(
            AnalysisItem(
                key=key,
                count=len(group),
                incident_ids=tuple(sorted(row.incident_id for row in group if row.incident_id))[
                    : request.limit
                ],
            )
            for key, group in ordered[: min(request.limit, maximum_groups)]
            if len(group) >= request.minimum_count
        )
    documents = tuple(sorted({row.document_id for row in selected}, key=str))
    incidents = tuple(sorted(row.incident_id for row in selected if row.incident_id))
    summary = _summary(operation, len(selected), items, scalar, stats, incidents)
    return AnalysisResult(
        operation=operation,
        row_count_considered=len(selected),
        row_count_excluded=len(rows) - len(selected),
        items=items,
        scalar_value=scalar,
        statistics=stats,
        summary=summary,
        provenance=AnalysisProvenance(
            source_document_ids=documents,
            supporting_incident_ids=incidents,
            formula=formula,
            taxonomy_version=TAXONOMY_VERSION
            if operation is AnalysisOperation.RECURRING_ROOT_CAUSES
            else None,
            algorithm_version=ALGORITHM_VERSION,
        ),
        request_id=request_id,
        trace_id=trace_id,
    )


def _operation_field(operation: AnalysisOperation, request: AnalysisRequest) -> str:
    fixed = {
        AnalysisOperation.SEVERITY_DISTRIBUTION: "severity",
        AnalysisOperation.STATUS_DISTRIBUTION: "status",
        AnalysisOperation.DEPARTMENT_DISTRIBUTION: "department",
        AnalysisOperation.DOCUMENT_TYPE_DISTRIBUTION: "document_type",
        AnalysisOperation.RECURRING_ROOT_CAUSES: "root_cause_category",
        AnalysisOperation.CORRECTIVE_ACTION_SUMMARY: "corrective_action_status",
        AnalysisOperation.MISSING_VALUE_SUMMARY: "severity",
    }
    return fixed.get(operation) or request.group_by or request.field or ""


def _date_key(value: date, interval: str) -> str:
    if interval == "day":
        return value.isoformat()
    if interval == "year":
        return str(value.year)
    if interval == "quarter":
        return f"{value.year}-Q{((value.month - 1) // 3) + 1}"
    return f"{value.year}-{value.month:02d}"


def _counter_items(
    counter: Counter[str], rows: tuple[IncidentAnalysisRow, ...], key: object, limit: int
) -> tuple[AnalysisItem, ...]:
    del rows, key
    return tuple(
        AnalysisItem(key=name, count=count) for name, count in sorted(counter.items())[:limit]
    )


def _summary(
    operation: AnalysisOperation,
    count: int,
    items: tuple[AnalysisItem, ...],
    scalar: float | int | None,
    stats: dict[str, float],
    incidents: tuple[str, ...],
) -> str:
    if scalar is not None:
        return f"The authorized dataset contains {int(scalar)} incident records."
    if stats:
        return (
            f"Duration statistics were calculated across {count} authorized incidents "
            "with valid values."
        )
    if items:
        summary = (
            f"The leading {operation.value} category is {items[0].key}, "
            f"appearing in {items[0].count} authorized incidents."
        )
        if operation is AnalysisOperation.RECURRING_ROOT_CAUSES and incidents:
            return f"{summary} Supporting incidents: {', '.join(incidents[:10])}."
        return summary
    return "The authorized dataset produced no result items for the requested operation."
