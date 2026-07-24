"""Bounded enterprise-identifier extraction tests."""

from enterprise_ai.retrieval.identifiers import (
    MAX_ENTERPRISE_IDENTIFIERS,
    extract_enterprise_identifiers,
)


def test_incident_identifier_normalizes_case_and_surrounding_punctuation() -> None:
    variants = (
        "inc-pay-2025-126",
        "INC-PAY-2025-126?",
        "\u201cINC-PAY-2025-126\u201d",
        "incident INC-PAY-2025-126.",
    )

    assert {extract_enterprise_identifiers(value)[0].normalized for value in variants} == {
        "INC-PAY-2025-126"
    }
    assert extract_enterprise_identifiers(variants[0])[0].original == "inc-pay-2025-126"


def test_identifier_extraction_is_deduplicated_bounded_and_format_owned() -> None:
    repeated = " ".join(f"INC-PAY-2025-{index:03d}" for index in range(100, 110))
    extracted = extract_enterprise_identifiers(repeated + " inc-pay-2025-100")

    assert len(extracted) == MAX_ENTERPRISE_IDENTIFIERS
    assert len({item.normalized for item in extracted}) == MAX_ENTERPRISE_IDENTIFIERS
    assert extract_enterprise_identifiers("INC-PAY-25-126") == ()
    assert extract_enterprise_identifiers("TICKET-PAY-2025-126") == ()


def test_identifier_extraction_has_a_bounded_input_window() -> None:
    value = ("x" * 4_001) + " INC-PAY-2025-126"

    assert extract_enterprise_identifiers(value) == ()
