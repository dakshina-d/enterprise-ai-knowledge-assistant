"""Document-level baseline metrics for live dense retrieval."""

import asyncio
import json
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from enterprise_ai.models.identity import AuthenticatedPrincipal, UserIdentity, UserRole
from enterprise_ai.security.authorization import AuthorizationService


def assessment_principal(role: UserRole) -> AuthenticatedPrincipal:
    now = datetime.now(UTC)
    authorization = AuthorizationService()
    return AuthenticatedPrincipal(
        identity=UserIdentity(
            user_id=uuid5(NAMESPACE_URL, f"retrieval-cli:{role.value}"),
            username=f"assessment-{role.value}",
            display_name=f"Assessment {role.value}",
            role=role,
        ),
        permissions=authorization.permissions_for_role(role),
        authenticated_at=now,
        expires_at=now + timedelta(hours=1),
    )


async def evaluate_dense_retrieval(
    service: Any,
    *,
    questions_path: Path,
    output_path: Path | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    raw = json.loads(await asyncio.to_thread(questions_path.read_text, encoding="utf-8"))
    selected = [
        item
        for item in raw
        if item.get("expected_access_outcome") == "allow"
        and item.get("expected_route") in {"simple_retrieval", "hybrid_retrieval"}
    ]
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    authorization_violations = 0
    missing_attribution = 0
    malformed_results = 0
    reciprocal_ranks: list[float] = []
    recalls: dict[int, list[float]] = {1: [], 3: [], 5: []}
    for item in selected:
        role = UserRole(str(item["required_role"]))
        started = clock()
        result = await service.retrieve(assessment_principal(role), str(item["question"]), top_k=5)
        latency = max(0.0, clock() - started)
        latencies.append(latency)
        retrieved = [str(evidence.document_id) for evidence in result.evidence]
        relevant = set(item["relevant_document_ids"])
        first_rank = next(
            (rank for rank, document_id in enumerate(retrieved, 1) if document_id in relevant), None
        )
        reciprocal_ranks.append(1 / first_rank if first_rank else 0.0)
        for cutoff in recalls:
            recalls[cutoff].append(float(bool(relevant.intersection(retrieved[:cutoff]))))
        authorization_violations += result.dropped_unauthorized
        malformed_results += result.malformed_results
        missing_attribution += sum(not evidence.source_file for evidence in result.evidence)
        rows.append(
            {
                "question_id": item["question_id"],
                "retrieved_document_ids": retrieved,
                "first_relevant_rank": first_rank,
            }
        )
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "question_count": len(rows),
        "recall_at_1": statistics.fmean(recalls[1]) if rows else 0.0,
        "recall_at_3": statistics.fmean(recalls[3]) if rows else 0.0,
        "recall_at_5": statistics.fmean(recalls[5]) if rows else 0.0,
        "mean_reciprocal_rank": statistics.fmean(reciprocal_ranks) if rows else 0.0,
        "authorization_violations": authorization_violations,
        "missing_attribution_count": missing_attribution,
        "malformed_result_count": malformed_results,
        "latency_seconds": {
            "minimum": min(latencies, default=0.0),
            "mean": statistics.fmean(latencies) if latencies else 0.0,
            "maximum": max(latencies, default=0.0),
        },
        "questions": rows,
    }
    if output_path:
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            output_path.write_text,
            json.dumps(report, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return report
