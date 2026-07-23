"""Small safe Streamlit rendering functions."""

import streamlit as st

from frontend.enterprise_ai_frontend.models import ActivityItem, ChatMessage


def render_message(message: ChatMessage) -> None:
    with st.chat_message(message.role):
        st.markdown(message.content)
        if message.completion_status is not None:
            st.caption(f"Completion: {message.completion_status.value.replace('_', ' ')}")
        if message.insufficient_evidence:
            st.warning("The available authorized evidence was insufficient.")
        if message.deterministic_fallback_used:
            st.info("A deterministic fallback response was used.")
        if message.citations:
            with st.expander("Sources", expanded=False):
                for citation in message.citations:
                    st.markdown(
                        f"**{citation.marker} — {citation.title}**  \n"
                        f"Section: {citation.section} · Version: {citation.version} · "
                        f"Updated: {citation.updated_date}"
                    )
        elif message.role == "assistant":
            st.caption("No document citations were provided.")
        if message.mcp_provenance is not None:
            provenance = message.mcp_provenance
            with st.expander("Enterprise data provenance", expanded=False):
                st.write(f"Tool: `{provenance.tool_name}`")
                st.write(f"Record: `{provenance.record_identifier}`")
                st.caption("Source: fictional read-only enterprise MCP data")
        if message.analysis_operation is not None:
            st.caption(f"Verified structured analysis: {message.analysis_operation}")
        if message.request_id is not None:
            st.caption(f"Request ID: {message.request_id}")


def render_activity_item(item: ActivityItem) -> None:
    icon = {
        "completed": "✅",
        "failed": "❌",
        "denied": "⛔",
        "warning": "⚠️",
        "started": "🔄",
        "running": "🔄",
        "accepted": "•",
    }.get(str(item.status), "•")
    st.write(f"{icon} **{item.label}**")
    if item.detail:
        st.caption(f"#{item.sequence} · {item.detail}")
    else:
        st.caption(f"#{item.sequence}")
