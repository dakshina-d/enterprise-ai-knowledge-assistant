import pytest
from enterprise_ai.research.evaluation import (
    evaluate_research,
    security_integrity_failures,
)


@pytest.mark.asyncio
async def test_twelve_question_final_pipeline_is_repeatable_and_secure() -> None:
    first = await evaluate_research()
    second = await evaluate_research()

    assert first == second
    assert first["research_question_count"] == 12
    assert not security_integrity_failures(first)
    assert first["citation_validation_pass_rate"] == 1.0
    assert first["analysis_provenance_validity_rate"] == 1.0
