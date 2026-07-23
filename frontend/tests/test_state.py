"""Per-session chat state, cleanup, and idempotency tests."""

from datetime import UTC, datetime
from uuid import uuid4

from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.models.events import AgentEventStatus
from enterprise_ai.models.identity import LoginResponse

from frontend.enterprise_ai_frontend.models import ActivityItem
from frontend.enterprise_ai_frontend.state import (
    ACCESS_TOKEN,
    ACTIVITY,
    MESSAGES,
    SESSION_ID,
    USER,
    activity,
    add_activity,
    add_user_message,
    authenticate,
    clear_all,
    complete,
    initialize,
    messages,
    new_conversation,
)


def test_authentication_new_conversation_and_logout(
    login_response: LoginResponse,
) -> None:
    state: dict[str, object] = {}
    initialize(state)
    authenticate(state, login_response)
    add_user_message(state, "hello")
    state[SESSION_ID] = uuid4()
    new_conversation(state)

    assert state[ACCESS_TOKEN] == login_response.access_token
    assert state[USER] is not None
    assert state[SESSION_ID] is None
    assert state[MESSAGES] == []
    clear_all(state)
    assert state[ACCESS_TOKEN] is None
    assert state[USER] is None
    assert state[ACTIVITY] == []


def test_user_and_assistant_messages_are_added_once(
    graph_output: GraphOutput,
) -> None:
    state: dict[str, object] = {}
    initialize(state)
    add_user_message(state, "hello")
    first = complete(state, graph_output)
    second = complete(state, graph_output)

    assert first == second
    assert [item.role for item in messages(state)] == ["user", "assistant"]
    assert state[SESSION_ID] == graph_output.session_id


def test_activity_is_deduplicated_and_bounded() -> None:
    state: dict[str, object] = {}
    initialize(state)
    items = [
        ActivityItem(
            event_id=uuid4(),
            sequence=index,
            timestamp=datetime.now(UTC),
            event_type="node.started",
            label="Agent activity",
            status=AgentEventStatus.STARTED,
        )
        for index in range(5)
    ]
    for item in items:
        add_activity(state, item, maximum_items=3)
    add_activity(state, items[-1], maximum_items=3)
    assert [item.sequence for item in activity(state)] == [2, 3, 4]
