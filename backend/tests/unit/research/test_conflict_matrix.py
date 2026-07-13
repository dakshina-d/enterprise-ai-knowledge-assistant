import pytest
from enterprise_ai.research.aggregation import aggregate_evidence
from enterprise_ai.research.conflicts import detect_conflicts

from .evidence_fixtures import evidence, result


@pytest.mark.parametrize(
    ("lower", "higher"), (("draft", "approved"), ("superseded", "active"), ("retired", "active"))
)
def test_status_conflicts_preserve_both_and_prefer_authority(lower: str, higher: str) -> None:
    first = evidence(1, status=lower, evidence_id=__import__("uuid").UUID(int=11))
    second = evidence(2, status=higher, evidence_id=__import__("uuid").UUID(int=12))
    ledger = aggregate_evidence(
        (result("T1", (first, second)),), maximum_items=5, maximum_characters=100
    )
    conflict = detect_conflicts(ledger)[0]
    assert len(conflict.evidence_ids) == 2
    assert conflict.preferred_evidence_id == second.evidence.evidence_id


def test_version_conflict_is_deterministic() -> None:
    ledger = aggregate_evidence(
        (result("T1", (evidence(1, version="1"), evidence(2, version="2"))),),
        maximum_items=5,
        maximum_characters=100,
    )
    assert detect_conflicts(ledger) == detect_conflicts(ledger)
