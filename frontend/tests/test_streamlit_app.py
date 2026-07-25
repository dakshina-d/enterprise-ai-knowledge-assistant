"""Offline Streamlit rendering smoke tests."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from enterprise_ai.llm.models import VerifiedCitation
from enterprise_ai.mcp_tools.models import MCPProvenance
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import AgentEventStatus
from enterprise_ai.models.identity import UserRole
from streamlit.testing.v1 import AppTest

from frontend.enterprise_ai_frontend.models import ActivityItem, ChatMessage, FrontendUser
from frontend.enterprise_ai_frontend.state import (
    ACCESS_TOKEN,
    ACTIVITY,
    LAST_ERROR,
    MESSAGES,
    USER,
)

APP_PATH = Path("frontend/streamlit_app.py")


def test_login_screen_renders_without_backend() -> None:
    app = AppTest.from_file(str(APP_PATH)).run()
    assert app.title[0].value == "Enterprise AI Knowledge Assistant"
    assert [item.label for item in app.text_input] == ["Username", "Password"]
    assert app.text_input[1].proto.type == 1
    assert app.button[0].label == "Sign in"


def test_authenticated_layout_history_and_logout() -> None:
    app = AppTest.from_file(str(APP_PATH))
    app.session_state[ACCESS_TOKEN] = "in-memory-test-token"
    app.session_state[USER] = FrontendUser(
        username="demo-viewer",
        display_name="Demo Viewer",
        role=UserRole.VIEWER,
    )
    app.session_state[MESSAGES] = []
    app.run()

    assert app.title[0].value == "Enterprise AI Knowledge Assistant"
    assert app.chat_input[0].disabled is False
    assert {button.label for button in app.button} >= {"New conversation", "Log out"}
    assert any("Role: viewer" in caption.value for caption in app.caption)

    next(button for button in app.button if button.label == "Log out").click()
    app.run()
    assert [item.label for item in app.text_input] == ["Username", "Password"]


def test_answer_citations_provenance_activity_and_error_render_safely() -> None:
    request_id = uuid4()
    citation = VerifiedCitation(
        marker="[1]",
        evidence_id=uuid4(),
        chunk_id=uuid4(),
        document_id=uuid4(),
        title="Fictional Password Policy",
        section="Rotation",
        source_file="private/path/policy.md",
        source_line_start=10,
        source_line_end=20,
        version="2.0",
        updated_date="2026-01-01",
        access_level="internal",
        department="Security",
        document_type="policy",
    )
    answer = ChatMessage(
        message_id=uuid4(),
        role="assistant",
        content="Use the approved fictional policy.",
        completion_status=ProcessingStatus.COMPLETED,
        request_id=request_id,
        citations=(citation,),
        mcp_provenance=MCPProvenance(
            tool_name="get_service_profile",
            record_identifier="payment-gateway",
        ),
        analysis_operation="root_cause_frequency",
    )
    event = ActivityItem(
        event_id=uuid4(),
        sequence=1,
        timestamp=datetime.now(UTC),
        event_type="mcp.tool_selected",
        label="Enterprise data tool selected",
        status=AgentEventStatus.COMPLETED,
        detail="Tool: get_service_profile",
    )
    app = AppTest.from_file(str(APP_PATH))
    app.session_state[ACCESS_TOKEN] = "in-memory-test-token"
    app.session_state[USER] = FrontendUser(
        username="demo-analyst",
        display_name="Demo Analyst",
        role=UserRole.ANALYST,
    )
    app.session_state[MESSAGES] = [answer]
    app.session_state[ACTIVITY] = [event]
    app.session_state[LAST_ERROR] = "A safe retryable error."
    app.run()

    visible_text = "\n".join(
        str(element.value)
        for collection in (app.markdown, app.caption, app.error)
        for element in collection
    )
    assert "Use the approved fictional policy." in visible_text
    assert "Fictional Password Policy" in visible_text
    assert "get_service_profile" in visible_text
    assert "Enterprise data tool selected" in visible_text
    assert "A safe retryable error." in visible_text
    assert "private/path" not in visible_text
    assert "in-memory-test-token" not in visible_text


def test_denied_security_response_renders_status_without_private_detail() -> None:
    denied = ChatMessage(
        message_id=uuid4(),
        role="assistant",
        content=(
            "Secrets, credentials, private configuration, and protected instructions "
            "cannot be disclosed."
        ),
        completion_status=ProcessingStatus.DENIED,
        request_id=uuid4(),
    )
    app = AppTest.from_file(str(APP_PATH))
    app.session_state[ACCESS_TOKEN] = "in-memory-test-token"
    app.session_state[USER] = FrontendUser(
        username="demo-analyst",
        display_name="Demo Analyst",
        role=UserRole.ANALYST,
    )
    app.session_state[MESSAGES] = [denied]
    app.run()

    visible = "\n".join(
        str(element.value) for collection in (app.markdown, app.caption) for element in collection
    )
    assert "Completion: denied" in visible
    assert "cannot be disclosed" in visible
    assert "in-memory-test-token" not in visible
