"""Regression tests for the deterministic fictional enterprise corpus."""

import hashlib
import json
from collections import Counter
from datetime import date

import pytest

from scripts.generate_sample_documents import ROOT, expected_outputs, generate
from scripts.validate_sample_documents import ValidationFailure, parse_front_matter, validate

MANIFEST_PATH = ROOT / "data/sample_documents/manifest.json"


def _manifest() -> list[dict[str, object]]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_generator_is_deterministic_and_committed_output_is_current() -> None:
    first = expected_outputs()
    second = expected_outputs()
    assert first == second
    assert generate(check=True) == 0
    assert all(path.read_text(encoding="utf-8") == content for path, content in first.items())


def test_manifest_has_expected_type_department_access_and_role_coverage() -> None:
    manifest = _manifest()
    assert len(manifest) == 51
    assert Counter(item["document_type"] for item in manifest) == {
        "policy": 7,
        "architecture": 8,
        "runbook": 9,
        "incident": 16,
        "product_specification": 6,
        "meeting_note": 5,
    }
    assert {item["department"] for item in manifest} == {
        "payments",
        "digital_banking",
        "cybersecurity",
        "infrastructure",
        "operations",
        "risk_and_compliance",
        "customer_service",
        "data_and_analytics",
    }
    assert {item["access_level"] for item in manifest} == {
        "public",
        "internal",
        "confidential",
        "restricted",
    }
    roles = {role for item in manifest for role in item["allowed_roles"]}
    assert roles == {"viewer", "analyst", "administrator"}


def test_incident_period_payment_volume_and_recurring_root_causes() -> None:
    incidents = [item for item in _manifest() if item["document_type"] == "incident"]
    assert len(incidents) == 16
    assert sum(bool(item["payment_related"]) for item in incidents) >= 10
    dates = [date.fromisoformat(str(item["created_date"])) for item in incidents]
    assert min(dates) >= date(2025, 7, 1)
    assert max(dates) <= date(2026, 6, 30)
    root_causes = Counter(item["root_cause_category"] for item in incidents)
    assert root_causes["connection_pool_exhaustion"] >= 2
    assert root_causes["message_queue_backlog"] >= 2
    assert root_causes["database_lock_contention"] >= 2
    assert root_causes["capacity_planning_error"] >= 2


def test_relationships_status_challenges_and_hashes_are_reproducible() -> None:
    manifest = _manifest()
    ids = {item["document_id"] for item in manifest}
    statuses = Counter(item["status"] for item in manifest)
    assert statuses["superseded"] >= 1
    assert statuses["draft"] >= 1
    assert statuses["archived"] >= 1
    assert sum(len(item["related_document_ids"]) for item in manifest) >= 50
    for item in manifest:
        assert set(item["related_document_ids"]) <= ids
        path = ROOT / str(item["file_path"])
        _, body = parse_front_matter(path.read_text(encoding="utf-8"))
        assert hashlib.sha256(body.encode("utf-8")).hexdigest() == item["content_hash"]


def test_benchmarks_reference_valid_documents_and_required_question_exists() -> None:
    ids = {item["document_id"] for item in _manifest()}
    questions = json.loads((ROOT / "data/evaluation/research_questions.json").read_text())
    cases = json.loads((ROOT / "data/evaluation/access_control_cases.json").read_text())
    assert len(questions) == 12
    assert len(cases) == 8
    required_question = (
        "Summarize all outage reports related to payment failures during the last year "
        "and identify recurring root causes."
    )
    assert any(item["question"] == required_question for item in questions)
    assert all(set(item["relevant_document_ids"]) <= ids for item in questions)
    assert all(item["document_id"] in ids for item in cases)


def test_security_fixtures_are_isolated_and_valid_corpus_is_safe() -> None:
    manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
    fixture_manifest = json.loads((ROOT / "data/security_fixtures/manifest.json").read_text())
    assert len(fixture_manifest) == 9
    assert "data/security_fixtures" not in manifest_text
    assert all(not item["included_in_valid_manifest"] for item in fixture_manifest)
    assert validate()["total"] == 51


def test_parser_rejects_document_without_front_matter() -> None:
    with pytest.raises(ValidationFailure):
        parse_front_matter("# Missing metadata\n")
