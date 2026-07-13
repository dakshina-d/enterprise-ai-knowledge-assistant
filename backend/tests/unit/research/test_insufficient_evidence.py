import pytest
from enterprise_ai.llm.fake_provider import FakeLLMProvider
from enterprise_ai.llm.response_service import GroundedResponseService
from enterprise_ai.models.identity import UserRole
from enterprise_ai.research.coverage import assess_coverage
from enterprise_ai.research.models import CoverageStatus
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal

from .evidence_fixtures import evidence, result
from .test_compiled_rounds import ControlledService, ProposingWorker, _plan, _request


@pytest.mark.asyncio
async def test_forced_no_evidence_is_bounded_and_deterministic() -> None:
    worker = ProposingWorker()
    research = await ControlledService(
        RetrievalSettings(research_max_depth=1), _plan(), worker
    ).run(_request())
    assert research.coverage.status is CoverageStatus.INSUFFICIENT
    assert max(item.depth for item in research.worker_results) == 1
    assert not research.evidence_ledger.entries
    service = GroundedResponseService(FakeLLMProvider(), RetrievalSettings())
    response, _, validation, _ = await service.retrieval_response(
        "Compare recovery actions by the employee who approved each action.",
        (),
        assessment_principal(UserRole.ANALYST),
    )
    assert response.insufficient_evidence and validation.valid and not response.citations
    assert "employee" not in response.answer_text.casefold()


def test_missing_comparison_side_is_partial_and_named_safely() -> None:
    assessment = assess_coverage(
        _plan(2), (result("T01", (evidence(1),)),), 1, (), budget_exhausted=False
    )
    assert assessment.status is CoverageStatus.PARTIALLY_SUFFICIENT
    assert assessment.missing_dimensions == ("Initial dimension 2",)


def test_authorization_blocked_status_exposes_no_source_metadata() -> None:
    assessment = assess_coverage(
        _plan(),
        (),
        0,
        (),
        budget_exhausted=False,
        authorization_blocked=True,
    )
    assert assessment.status is CoverageStatus.BLOCKED_BY_AUTHORIZATION
    serialized = assessment.model_dump_json()
    assert "document_id" not in serialized and "title" not in serialized
