"""Centralized operations over one Streamlit session's presentation state."""

from collections.abc import MutableMapping
from typing import cast
from uuid import UUID, uuid4

from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.models.identity import LoginResponse

from frontend.enterprise_ai_frontend.models import (
    ActivityItem,
    ChatMessage,
    FrontendUser,
    RequestMetadata,
)

ACCESS_TOKEN = "access_token"  # noqa: S105 - session-state key, not a credential
USER = "authenticated_user"
SESSION_ID = "backend_session_id"
MESSAGES = "chat_messages"
ACTIVITY = "activity_items"
LAST_RESPONSE = "last_completed_response"
PENDING = "request_pending"
LAST_ERROR = "last_safe_error"
REQUEST_METADATA = "request_metadata"


StateStore = MutableMapping[str, object]


def initialize(state: StateStore) -> None:
    defaults: dict[str, object] = {
        ACCESS_TOKEN: None,
        USER: None,
        SESSION_ID: None,
        MESSAGES: [],
        ACTIVITY: [],
        LAST_RESPONSE: None,
        PENDING: False,
        LAST_ERROR: None,
        REQUEST_METADATA: None,
    }
    for key, value in defaults.items():
        state.setdefault(key, value)


def authenticate(state: StateStore, login: LoginResponse) -> None:
    clear_all(state)
    state[ACCESS_TOKEN] = login.access_token
    state[USER] = FrontendUser(
        username=login.user.username,
        display_name=login.user.display_name,
        role=login.user.role,
    )


def clear_all(state: StateStore) -> None:
    for key in (
        ACCESS_TOKEN,
        USER,
        SESSION_ID,
        MESSAGES,
        ACTIVITY,
        LAST_RESPONSE,
        PENDING,
        LAST_ERROR,
        REQUEST_METADATA,
    ):
        state.pop(key, None)
    initialize(state)


def new_conversation(state: StateStore) -> None:
    state[SESSION_ID] = None
    state[MESSAGES] = []
    state[ACTIVITY] = []
    state[LAST_RESPONSE] = None
    state[PENDING] = False
    state[LAST_ERROR] = None
    state[REQUEST_METADATA] = None


def add_user_message(state: StateStore, content: str) -> ChatMessage:
    message = ChatMessage(message_id=uuid4(), role="user", content=content)
    state[MESSAGES] = [*messages(state), message]
    return message


def add_activity(
    state: StateStore,
    item: ActivityItem,
    *,
    maximum_items: int,
) -> None:
    existing = activity(state)
    if any(candidate.event_id == item.event_id for candidate in existing):
        return
    state[ACTIVITY] = [*existing, item][-maximum_items:]


def complete(state: StateStore, output: GraphOutput) -> ChatMessage:
    existing = next(
        (
            message
            for message in messages(state)
            if message.role == "assistant" and message.request_id == output.request_id
        ),
        None,
    )
    if existing is not None:
        return existing
    operation = output.analysis_result.operation.value if output.analysis_result else None
    assistant = ChatMessage(
        message_id=uuid4(),
        role="assistant",
        content=output.response_text,
        completion_status=output.completion_status,
        request_id=output.request_id,
        citations=output.citations,
        mcp_provenance=output.mcp_provenance,
        analysis_operation=operation,
        insufficient_evidence=output.insufficient_evidence,
        deterministic_fallback_used=output.deterministic_fallback_used,
        deterministic_analysis_rendering_used=(output.deterministic_analysis_rendering_used),
        fallback_reason=output.fallback_reason,
        analysis_result=output.analysis_result,
    )
    state[MESSAGES] = [*messages(state), assistant]
    state[SESSION_ID] = output.session_id
    state[LAST_RESPONSE] = output
    state[REQUEST_METADATA] = RequestMetadata(
        request_id=output.request_id,
        trace_id=output.trace_id,
        session_id=output.session_id,
    )
    state[PENDING] = False
    state[LAST_ERROR] = None
    return assistant


def messages(state: StateStore) -> list[ChatMessage]:
    return list(cast(list[ChatMessage], state.get(MESSAGES, [])))


def activity(state: StateStore) -> list[ActivityItem]:
    return list(cast(list[ActivityItem], state.get(ACTIVITY, [])))


def token(state: StateStore) -> str | None:
    value = state.get(ACCESS_TOKEN)
    return value if isinstance(value, str) else None


def session_id(state: StateStore) -> UUID | None:
    value = state.get(SESSION_ID)
    return value if isinstance(value, UUID) else None
