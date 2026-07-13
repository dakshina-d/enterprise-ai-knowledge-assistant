from enterprise_ai.research.aggregation import aggregate_evidence

from .evidence_fixtures import evidence, result


def test_valid_duplicates_merge_provenance_and_best_rank_without_mutation() -> None:
    first = evidence(1)
    second = first.model_copy(update={"final_rank": 1, "hybrid_score": 0.8})
    ledger = aggregate_evidence(
        (result("T2", (first,)), result("T1", (second,))), maximum_items=5, maximum_characters=100
    )
    assert len(ledger.entries) == 1
    assert ledger.entries[0].task_ids == ("T1", "T2")
    assert ledger.entries[0].evidence.final_rank == 1
    assert first.final_rank == 2


def test_conflicting_identity_and_attribution_are_dropped() -> None:
    first = evidence(1)
    conflict = evidence(
        1, evidence_id=first.evidence.evidence_id, document_id=__import__("uuid").UUID(int=999)
    )
    ledger = aggregate_evidence(
        (result("T1", (first,)), result("T2", (conflict,))), maximum_items=5, maximum_characters=100
    )
    assert len(ledger.entries) == 1 and ledger.dropped_items == 1


def test_stale_build_is_dropped() -> None:
    ledger = aggregate_evidence(
        (result("T1", (evidence(1),)),),
        maximum_items=5,
        maximum_characters=100,
        expected_build_fingerprint="c" * 64,
    )
    assert not ledger.entries and ledger.dropped_items == 1


def test_item_and_utf8_character_limits_are_deterministic() -> None:
    item = evidence(1, text="éé")
    exact = aggregate_evidence((result("T1", (item,)),), maximum_items=1, maximum_characters=4)
    exceeded = aggregate_evidence(
        (result("T1", (item, evidence(2))),), maximum_items=1, maximum_characters=3
    )
    assert len(exact.entries) == 1 and exact.total_characters == 4
    assert not exceeded.entries and exceeded.dropped_items == 2
