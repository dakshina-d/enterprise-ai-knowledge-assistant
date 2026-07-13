import asyncio
import json
from pathlib import Path

import pytest
from enterprise_ai.llm.models import (
    GroundedAnswerDraft,
    GroundedClaim,
    LLMGenerationResult,
    LLMProviderMetadata,
)
from enterprise_ai.llm.response_service import GroundedResponseService
from enterprise_ai.models.identity import UserRole
from enterprise_ai.research.budgets import BudgetLedger
from enterprise_ai.research.models import ResearchBudget
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal

from .evidence_fixtures import evidence


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: object) -> LLMGenerationResult:
        self.calls += 1
        return LLMGenerationResult(
            draft=GroundedAnswerDraft(
                answer_summary="Unsafe draft",
                claims=(
                    GroundedClaim(
                        claim_id="C1",
                        text="Invented claim",
                        supporting_evidence_ids=("E999",),
                    ),
                ),
            ),
            metadata=LLMProviderMetadata(provider="fake", model="fake"),
        )

    async def close(self) -> None:
        return None


def _budget(limit: int) -> ResearchBudget:
    return ResearchBudget(
        maximum_depth=1,
        maximum_total_tasks=1,
        maximum_retrieval_calls=1,
        maximum_analysis_calls=0,
        maximum_llm_calls=limit,
        maximum_evidence_items=1,
        maximum_evidence_characters=100,
    )


@pytest.mark.asyncio
async def test_exhaustion_before_synthesis_uses_deterministic_fallback() -> None:
    provider = CountingProvider()
    service = GroundedResponseService(provider, RetrievalSettings())
    response, _, validation, repairs = await service.retrieval_response(
        "question",
        (evidence(1),),
        assessment_principal(UserRole.VIEWER),
        maximum_provider_calls=0,
    )
    assert provider.calls == 0 and repairs == 0 and validation.valid
    assert response.deterministic_fallback_used


@pytest.mark.asyncio
async def test_no_remaining_call_prevents_citation_repair_and_hides_invalid_id(
    tmp_path: Path,
) -> None:
    provider = CountingProvider()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"build_fingerprint": "b" * 64}), encoding="utf-8")
    service = GroundedResponseService(provider, RetrievalSettings(ingestion_manifest_path=manifest))
    response, _, _, repairs = await service.retrieval_response(
        "question",
        (evidence(1),),
        assessment_principal(UserRole.VIEWER),
        maximum_provider_calls=1,
    )
    assert provider.calls == 1 and repairs == 0
    assert "E999" not in response.answer_text and response.deterministic_fallback_used


@pytest.mark.asyncio
async def test_concurrent_final_reservation_is_atomic_and_request_local() -> None:
    first = BudgetLedger(_budget(1))
    outcomes = await asyncio.gather(*(first.consume("llm_calls") for _ in range(2)))
    second = BudgetLedger(_budget(1))
    assert outcomes.count(True) == 1 and (await first.usage()).llm_calls == 1
    assert await second.consume("llm_calls")
