"""Privacy tests for trace metadata."""

from enterprise_ai.observability.sanitization import sanitize_metadata


def test_sanitizer_only_keeps_bounded_allowlisted_scalar_values() -> None:
    result = sanitize_metadata(
        {
            "request_id": "r" * 300,
            "evidence_count": 2,
            "budget_exhausted": False,
            "api_key": "secret-value",
            "authorization": "Bearer jwt-value",
            "raw_evidence": "confidential text",
            "route": {"nested": "value"},
        }
    )

    assert result == {
        "budget_exhausted": False,
        "evidence_count": 2,
        "request_id": "r" * 256,
    }
    assert "secret-value" not in repr(result)
    assert "confidential text" not in repr(result)
