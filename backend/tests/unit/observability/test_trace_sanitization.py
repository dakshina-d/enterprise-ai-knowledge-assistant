"""Privacy tests for trace metadata."""

from enterprise_ai.observability.sanitization import sanitize_metadata


def test_sanitizer_only_keeps_bounded_allowlisted_scalar_values() -> None:
    result = sanitize_metadata(
        {
            "request_id": "r" * 300,
            "evidence_count": 2,
            "budget_exhausted": False,
            "exact_identifier_present": True,
            "aggregate_intent_present": False,
            "security_denial_category": "credential_exfiltration",
            "identifier_constraint_active": True,
            "api_key": "secret-value",
            "authorization": "Bearer jwt-value",
            "raw_evidence": "confidential text",
            "route": {"nested": "value"},
        }
    )

    assert result == {
        "budget_exhausted": False,
        "aggregate_intent_present": False,
        "evidence_count": 2,
        "exact_identifier_present": True,
        "identifier_constraint_active": True,
        "request_id": "r" * 256,
        "security_denial_category": "credential_exfiltration",
    }
    assert "secret-value" not in repr(result)
    assert "confidential text" not in repr(result)
