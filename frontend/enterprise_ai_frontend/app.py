"""Streamlit page orchestration for authenticated multi-turn chat."""

from typing import cast

import streamlit as st

from frontend.enterprise_ai_frontend.api_client import APIClient
from frontend.enterprise_ai_frontend.auth import render_login
from frontend.enterprise_ai_frontend.config import get_frontend_settings
from frontend.enterprise_ai_frontend.errors import (
    AuthenticationExpiredError,
    FrontendError,
)
from frontend.enterprise_ai_frontend.rendering import render_activity_item, render_message
from frontend.enterprise_ai_frontend.state import (
    ACCESS_TOKEN,
    ACTIVITY,
    LAST_ERROR,
    PENDING,
    SESSION_ID,
    USER,
    StateStore,
    activity,
    add_user_message,
    clear_all,
    initialize,
    messages,
    new_conversation,
    session_id,
    token,
)
from frontend.enterprise_ai_frontend.turns import handle_envelope


def run() -> None:
    settings = get_frontend_settings()
    st.set_page_config(page_title=settings.application_title, layout="wide")
    state = cast(StateStore, st.session_state)
    initialize(state)
    client = APIClient(settings)
    if token(state) is None:
        render_login(client)
        return

    user = st.session_state[USER]
    st.title(settings.application_title)
    st.caption("Authorization-aware knowledge, analysis, research, and enterprise data assistance.")

    with st.sidebar:
        st.subheader("Session")
        st.write(user.display_name)
        st.caption(f"Role: {user.role.value}")
        if st.button(
            "New conversation", use_container_width=True, disabled=st.session_state[PENDING]
        ):
            new_conversation(state)
            st.rerun()
        current_session = session_id(state)
        st.caption(
            f"Conversation: {str(current_session)[:8]}..."
            if current_session is not None
            else "Conversation: new"
        )
        st.caption("Status: running" if st.session_state[PENDING] else "Status: ready")
        st.divider()
        st.subheader("Agent Activity")
        records = activity(state)
        if records:
            with st.expander(
                "Current timeline",
                expanded=bool(st.session_state[PENDING]),
            ):
                for item in records:
                    render_activity_item(item)
        else:
            st.caption("Activity will appear when a request starts.")
        st.divider()
        if st.button("Log out", use_container_width=True, disabled=st.session_state[PENDING]):
            clear_all(state)
            st.rerun()

    for message in messages(state):
        render_message(message)
    if st.session_state[LAST_ERROR]:
        st.error(st.session_state[LAST_ERROR])

    prompt = st.chat_input(
        "Ask about enterprise knowledge or operations",
        disabled=st.session_state[PENDING],
        max_chars=4_000,
    )
    if prompt is None:
        return
    prompt = prompt.strip()
    if not prompt:
        st.warning("Enter a non-empty message.")
        return

    add_user_message(state, prompt)
    st.session_state[PENDING] = True
    st.session_state[LAST_ERROR] = None
    st.session_state[ACTIVITY] = []
    with st.chat_message("user"):
        st.markdown(prompt)
    status = st.status("Assistant is working...", expanded=True)
    try:
        for envelope in client.stream_chat(
            access_token=st.session_state[ACCESS_TOKEN],
            message=prompt,
            session_id=st.session_state[SESSION_ID],
        ):
            item, _ = handle_envelope(
                state,
                envelope,
                maximum_activity_items=settings.maximum_activity_items,
            )
            with status:
                render_activity_item(item)
        status.update(label="Request completed", state="complete", expanded=False)
    except AuthenticationExpiredError as error:
        clear_all(state)
        st.session_state[LAST_ERROR] = error.public_message
        st.rerun()
    except FrontendError as error:
        st.session_state[PENDING] = False
        suffix = (
            f" Try again in {error.retry_after_seconds} seconds."
            if error.retry_after_seconds is not None
            else ""
        )
        st.session_state[LAST_ERROR] = f"{error.public_message}{suffix}"
        status.update(label="Request failed", state="error", expanded=True)
    else:
        st.rerun()
