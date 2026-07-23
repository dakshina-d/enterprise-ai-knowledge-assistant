"""Small JSON logging foundation without third-party runtime dependencies."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

_ALLOWED_EXTRA_FIELDS = frozenset(
    {
        "request_id",
        "trace_id",
        "session_id",
        "endpoint",
        "method",
        "role",
        "selected_route",
        "route",
        "completion_status",
        "status",
        "dependency_category",
        "duration_category",
        "outcome",
        "cancelled",
        "disconnected",
    }
)
_SECRET = re.compile(
    r"(?i)(authorization:\s*bearer\s+\S+|bearer\s+\S+|"
    r"sk-[A-Za-z0-9_-]{20,}|(?:password|api[_-]?key|secret|token)\s*[:=]\s*\S+)"
)
_INTERNAL_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:home|Users|var|tmp)/)\S+", re.I)


class JsonFormatter(logging.Formatter):
    """Serialize standard log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _safe_message(record.getMessage()),
        }
        for field in _ALLOWED_EXTRA_FIELDS:
            if hasattr(record, field):
                value = getattr(record, field)
                payload[field] = getattr(value, "value", value)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Configure the root logger with deterministic JSON output."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


def _safe_message(message: str) -> str:
    normalized = " ".join(message.split())[:500]
    return _INTERNAL_PATH.sub("[REDACTED_PATH]", _SECRET.sub("[REDACTED]", normalized))
