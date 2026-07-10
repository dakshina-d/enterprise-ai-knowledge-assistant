"""Reusable validation helpers for safe public and boundary models."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from pydantic import SecretStr

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def reject_blank_text(value: str) -> str:
    """Reject empty or whitespace-only text without altering valid input."""
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


def validate_text_length(value: str, *, minimum: int = 1, maximum: int) -> str:
    """Validate text length and reject blank content."""
    reject_blank_text(value)
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"text length must be between {minimum} and {maximum}")
    return value


def ensure_utc_aware(value: datetime) -> datetime:
    """Require an aware datetime and normalize its representation to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value.astimezone(UTC)


def validate_json_compatible(
    value: object,
    *,
    maximum_depth: int = 5,
    maximum_bytes: int = 16_384,
) -> JsonValue:
    """Return a JSON-compatible value after enforcing depth and size bounds."""
    _validate_json_node(value, depth=0, maximum_depth=maximum_depth)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"JSON payload exceeds {maximum_bytes} bytes")
    return value  # type: ignore[return-value]


def _validate_json_node(value: object, *, depth: int, maximum_depth: int) -> None:
    if depth > maximum_depth:
        raise ValueError(f"JSON payload exceeds maximum depth {maximum_depth}")
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, SecretStr):
        raise ValueError("secret values are not supported in public payloads")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _validate_json_node(item, depth=depth + 1, maximum_depth=maximum_depth)
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for item in value:
            _validate_json_node(item, depth=depth + 1, maximum_depth=maximum_depth)
        return
    raise ValueError(f"unsupported JSON value type: {type(value).__name__}")
