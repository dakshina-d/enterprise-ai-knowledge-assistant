"""Pure per-envelope chat-turn state transitions shared by the Streamlit page and tests."""

from enterprise_ai.api.schemas import ChatStreamEnvelope

from frontend.enterprise_ai_frontend.activity import activity_from_envelope
from frontend.enterprise_ai_frontend.errors import FrontendError, SSEProtocolError
from frontend.enterprise_ai_frontend.models import ActivityItem
from frontend.enterprise_ai_frontend.state import (
    StateStore,
    add_activity,
    complete,
    record_error,
)


def handle_envelope(
    state: StateStore,
    envelope: ChatStreamEnvelope,
    *,
    maximum_activity_items: int,
) -> tuple[ActivityItem, bool]:
    """Record safe activity and commit any validated graph-owned terminal output."""
    item = activity_from_envelope(envelope)
    add_activity(state, item, maximum_items=maximum_activity_items)
    if envelope.event_type == "stream.error":
        if envelope.error is None:
            raise SSEProtocolError()
        record_error(state, envelope.error.message)
        raise FrontendError(
            envelope.error.message,
            code=envelope.error.code,
            retryable=envelope.error.retryable,
        )
    if envelope.event_type == "response.failed":
        if envelope.response is None:
            raise SSEProtocolError("The failed stream did not contain a final response.")
        complete(state, envelope.response)
        return item, True
    if envelope.event_type == "response.completed":
        if envelope.response is None:
            raise SSEProtocolError("The completed stream did not contain a final response.")
        complete(state, envelope.response)
        return item, True
    return item, False
