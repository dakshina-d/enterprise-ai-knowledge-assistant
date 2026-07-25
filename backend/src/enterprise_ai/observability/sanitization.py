"""Allowlisted, bounded trace metadata sanitization."""

from collections.abc import Mapping
from enum import Enum
from uuid import UUID

SAFE_KEYS = frozenset(
    {
        "application_version",
        "graph_version",
        "environment",
        "user_role",
        "route",
        "permission_count",
        "request_id",
        "trace_id",
        "session_id",
        "planner_version",
        "retrieval_mode",
        "task_id",
        "parent_task_id",
        "round",
        "depth",
        "task_status",
        "evidence_count",
        "excluded_count",
        "retrieval_calls",
        "analysis_calls",
        "llm_calls",
        "budget_exhausted",
        "coverage_status",
        "completion_status",
        "citation_valid",
        "deterministic_fallback_used",
        "deterministic_analysis_rendering_used",
        "fallback_used",
        "fallback_reason",
        "fallback_strategy",
        "selected_passage_count",
        "supported_concept_count",
        "insufficient_evidence",
        "model",
        "build_fingerprint",
        "query_characters",
        "query_fingerprint",
        "top_k",
        "filter_present",
        "exact_identifier_present",
        "aggregate_intent_present",
        "security_denial_category",
        "identifier_constraint_active",
        "stale_count",
        "conflict_count",
        "root_task_count",
        "child_task_count",
        "maximum_depth",
        "provider",
        "attempt",
        "server_name",
        "tool_name",
        "result_status",
        "result_count",
        "timeout_category",
        "protocol_version",
        "transport_type",
    }
)


def sanitize_metadata(values: Mapping[str, object]) -> dict[str, str | int | float | bool | None]:
    result: dict[str, str | int | float | bool | None] = {}
    for key in sorted(set(values).intersection(SAFE_KEYS)):
        value = values[key]
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, UUID):
            value = str(value)
        if value is None or isinstance(value, (int, float, bool)):
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:256]
    return result
