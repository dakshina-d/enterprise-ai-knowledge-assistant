"""Versioned deterministic root-cause taxonomy."""

ROOT_CAUSE_CATEGORIES = (
    "connection_pool_exhaustion",
    "certificate_lifecycle_failure",
    "message_queue_backlog",
    "third_party_gateway_timeout",
    "configuration_drift",
    "retry_storm",
    "database_lock_contention",
    "dns_service_discovery_failure",
    "capacity_planning_error",
    "monitoring_gap",
    "deployment_regression",
    "manual_operational_error",
    "other",
    "unknown",
)

_RULES = {
    "connection_pool_exhaustion": ("connection pool", "connection slots"),
    "certificate_lifecycle_failure": ("certificate",),
    "message_queue_backlog": ("queue backlog", "queue age"),
    "third_party_gateway_timeout": ("third party", "provider timeout", "gateway timeout"),
    "configuration_drift": ("configuration drift",),
    "retry_storm": ("retry storm", "retry amplification"),
    "database_lock_contention": ("lock contention", "database lock"),
    "dns_service_discovery_failure": ("dns", "service discovery"),
    "capacity_planning_error": ("capacity planning", "capacity shortfall"),
    "monitoring_gap": ("monitoring gap", "missing alert"),
    "deployment_regression": ("deployment regression",),
    "manual_operational_error": ("manual error", "operator error"),
}


def classify_root_cause(text: str | None) -> str:
    if not text:
        return "unknown"
    value = text.casefold()
    for category, phrases in _RULES.items():
        if any(phrase in value for phrase in phrases):
            return category
    return "other"
