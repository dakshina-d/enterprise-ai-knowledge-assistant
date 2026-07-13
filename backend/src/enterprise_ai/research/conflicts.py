"""Conservative structural conflict detection."""

from collections import defaultdict

from enterprise_ai.research.models import ResearchConflict, ResearchEvidenceLedger
from enterprise_ai.retrieval.dense_retriever import DenseEvidence


def detect_conflicts(ledger: ResearchEvidenceLedger) -> tuple[ResearchConflict, ...]:
    versions: defaultdict[object, list[DenseEvidence]] = defaultdict(list)
    for entry in ledger.entries:
        versions[entry.evidence.evidence.document_id].append(entry.evidence.evidence)
    conflicts = []
    for items in versions.values():
        version_values = {item.version for item in items}
        status_values = {item.status.casefold() for item in items}
        if (
            len(version_values) > 1
            or ({"draft", "approved"} <= status_values)
            or ({"active", "superseded"} <= status_values)
            or ({"active", "retired"} <= status_values)
        ):
            authority = {
                "approved": 0,
                "active": 1,
                "final": 2,
                "post_incident_final": 3,
                "draft": 8,
                "superseded": 9,
                "retired": 10,
            }
            preferred = min(
                items,
                key=lambda item: (
                    authority.get(item.status.casefold(), 5),
                    -item.updated_date.toordinal(),
                    str(item.evidence_id),
                ),
            )
            conflicts.append(
                ResearchConflict(
                    conflict_type="document_version_or_status",
                    evidence_ids=tuple(sorted({item.evidence_id for item in items}, key=str)),
                    description=(
                        "Authorized evidence contains differing versions or lifecycle statuses."
                    ),
                    preferred_evidence_id=preferred.evidence_id,
                )
            )
    return tuple(sorted(conflicts, key=lambda item: tuple(map(str, item.evidence_ids))))
