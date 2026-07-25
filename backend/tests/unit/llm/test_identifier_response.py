"""Generated-response enterprise identifier preservation tests."""

import pytest
from enterprise_ai.graph.dependencies import OfflineSparseAdapter
from enterprise_ai.llm.fake_provider import FakeLLMProvider
from enterprise_ai.llm.identifier_validator import (
    validate_and_repair_response_identifiers,
)
from enterprise_ai.llm.models import GroundedAnswerDraft, GroundedClaim
from enterprise_ai.llm.response_service import GroundedResponseService, render_draft
from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.filters import DenseQueryFilters
from enterprise_ai.retrieval.sparse.retriever import SparseRetrievalService

_EXACT = "INC-PAY-2025-126"
_OTHER = "INC-PAY-2025-097"
_QUERY = (
    f"According to {_EXACT}, who is the primary owner, which supporting owners "
    "are listed, and what is the follow-up status?"
)


def _draft(summary: str, text: str, evidence_id: str = "E1") -> GroundedAnswerDraft:
    return GroundedAnswerDraft(
        answer_summary=summary,
        claims=(
            GroundedClaim(
                claim_id="C1",
                text=text,
                supporting_evidence_ids=(evidence_id,),
            ),
        ),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "INC-PAY-2025-12-6",
        "INC PAY 2025 126",
        "INC-PAY-2025-0126",
    ),
)
def test_unambiguous_near_identifier_in_claim_is_repaired_without_touching_citation(
    mutation: str,
) -> None:
    result = validate_and_repair_response_identifiers(
        _draft(
            f"Ownership for {_EXACT}.",
            f"The primary owner for {mutation} is Cybersecurity service owner.",
        ),
        ((_EXACT, ("E1",)),),
    )

    assert result.errors == ()
    assert result.repair_count == 1
    assert _EXACT in result.draft.claims[0].text
    assert mutation not in result.draft.claims[0].text
    assert result.draft.claims[0].supporting_evidence_ids == ("E1",)
    assert f"The primary owner for {_EXACT} is Cybersecurity service owner. [E1]" in render_draft(
        result.draft
    )


def test_unambiguous_near_identifier_in_answer_summary_is_repaired() -> None:
    result = validate_and_repair_response_identifiers(
        _draft(
            "The requested record is INC-PAY-2025-12-6.",
            "The primary owner is Cybersecurity service owner.",
        ),
        ((_EXACT, ("E1",)),),
    )

    assert result.errors == ()
    assert result.draft.answer_summary == f"The requested record is {_EXACT}."
    assert "INC-PAY-2025-12-6" not in render_draft(result.draft)


def test_canonical_identifier_is_byte_for_byte_unchanged() -> None:
    draft = _draft(
        f"Ownership for {_EXACT}.",
        f"The primary owner for {_EXACT} is Cybersecurity service owner.",
    )

    result = validate_and_repair_response_identifiers(draft, ((_EXACT, ("E1",)),))

    assert result.draft == draft
    assert result.errors == ()
    assert result.repair_count == 0


def test_unsupported_valid_identifier_is_rejected() -> None:
    result = validate_and_repair_response_identifiers(
        _draft(f"Ownership for {_OTHER}.", f"The primary owner for {_OTHER} is another team."),
        ((_EXACT, ("E1",)),),
    )

    assert result.errors
    assert _OTHER in render_draft(result.draft)


def test_unknown_requested_identifier_does_not_substitute_a_known_identifier() -> None:
    result = validate_and_repair_response_identifiers(
        GroundedAnswerDraft(answer_summary=f"No evidence for {_OTHER}."),
        (("INC-PAY-2099-999", ()),),
    )

    assert result.errors
    assert "INC-PAY-2099-999" not in result.draft.answer_summary


def test_multiple_identifiers_preserve_mapping_and_claim_swaps_are_rejected() -> None:
    requirements = ((_EXACT, ("E1",)), (_OTHER, ("E2",)))
    aligned = GroundedAnswerDraft(
        answer_summary=f"Comparison of {_EXACT} and {_OTHER}.",
        claims=(
            GroundedClaim(
                claim_id="C1",
                text=f"{_EXACT} has the first owner.",
                supporting_evidence_ids=("E1",),
            ),
            GroundedClaim(
                claim_id="C2",
                text=f"{_OTHER} has the second owner.",
                supporting_evidence_ids=("E2",),
            ),
        ),
    )
    swapped = aligned.model_copy(
        update={
            "claims": (
                aligned.claims[0].model_copy(update={"text": f"{_OTHER} has the first owner."}),
                aligned.claims[1].model_copy(update={"text": f"{_EXACT} has the second owner."}),
            )
        }
    )

    aligned_result = validate_and_repair_response_identifiers(aligned, requirements)
    swapped_result = validate_and_repair_response_identifiers(swapped, requirements)

    assert aligned_result.draft == aligned
    assert aligned_result.errors == ()
    assert swapped_result.errors


def test_ambiguous_near_identifier_is_not_guessed() -> None:
    result = validate_and_repair_response_identifiers(
        _draft(
            "Two identifiers were requested.",
            "The owner for INC-PAY-2025-12-6 is not safely attributable.",
        ),
        ((_EXACT, ("E1",)), ("INC-PAY-2025-0126", ("E2",))),
    )

    assert result.errors
    assert "INC-PAY-2025-12-6" in result.draft.claims[0].text


def test_non_identifier_values_markers_and_uuids_are_unchanged() -> None:
    draft = _draft(
        f"{_EXACT}.",
        (
            f"{_EXACT}. Date 2025-12-17; version v1.2.6; amount $1,260.50; "
            "ticket TICKET-126; marker E1; UUID 00000000-0000-4000-8000-000000000126."
        ),
    )

    result = validate_and_repair_response_identifiers(draft, ((_EXACT, ("E1",)),))

    assert result.draft == draft
    assert result.errors == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("retrieval_mode", ("sparse", "pinecone_hybrid"))
async def test_public_response_repair_is_identical_across_retrieval_modes(
    retrieval_mode: str,
) -> None:
    principal = assessment_principal(UserRole.ADMINISTRATOR)
    settings = RetrievalSettings().model_copy(update={"retrieval_mode": retrieval_mode})
    retrieved = await OfflineSparseAdapter(SparseRetrievalService(settings)).retrieve(
        principal,
        _QUERY,
        top_k=5,
        filters=DenseQueryFilters(),
    )
    provider = FakeLLMProvider(
        lambda request: _draft(
            f"Ownership for {_EXACT}.",
            "The primary owner for INC-PAY-2025-12-6 is Cybersecurity service owner.",
            request.allowed_evidence_ids[0],
        )
    )

    response, _, validation, repairs = await GroundedResponseService(
        provider,
        settings,
    ).retrieval_response(_QUERY, retrieved.evidence, principal)

    assert validation.valid
    assert repairs == 0
    assert response.provider == "fake"
    assert _EXACT in response.answer_text
    assert "INC-PAY-2025-12-6" not in response.answer_text
    assert "[E1]" in response.answer_text


@pytest.mark.asyncio
async def test_deterministic_fallback_never_returns_provider_substitution() -> None:
    principal = assessment_principal(UserRole.ADMINISTRATOR)
    settings = RetrievalSettings()
    retrieved = await OfflineSparseAdapter(SparseRetrievalService(settings)).retrieve(
        principal,
        _QUERY,
        top_k=5,
        filters=DenseQueryFilters(),
    )
    provider = FakeLLMProvider(
        lambda request: _draft(
            f"Ownership for {_OTHER}.",
            f"The primary owner for {_OTHER} is another team.",
            request.allowed_evidence_ids[0],
        )
    )

    response, _, _, repairs = await GroundedResponseService(
        provider,
        settings,
    ).retrieval_response(_QUERY, retrieved.evidence, principal)

    assert repairs == 1
    assert response.deterministic_fallback_used
    assert _OTHER not in response.answer_text
    assert _EXACT in response.answer_text
