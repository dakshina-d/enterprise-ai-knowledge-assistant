"""Pure frontend notice selection tests."""

from uuid import uuid4

from frontend.enterprise_ai_frontend.models import ChatMessage
from frontend.enterprise_ai_frontend.rendering import response_notices


def test_verified_analysis_notice_does_not_include_fallback_warning() -> None:
    message = ChatMessage(
        message_id=uuid4(),
        role="assistant",
        content="Verified result.",
        deterministic_analysis_rendering_used=True,
    )
    assert response_notices(message) == (
        "Verified structured analysis was rendered deterministically.",
    )
    assert all("fallback" not in notice.casefold() for notice in response_notices(message))


def test_true_fallback_notice_is_preserved() -> None:
    message = ChatMessage(
        message_id=uuid4(),
        role="assistant",
        content="Safe fallback.",
        deterministic_fallback_used=True,
    )
    assert response_notices(message) == ("A deterministic fallback response was used.",)
