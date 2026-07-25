"""Small safe Streamlit rendering functions."""

import streamlit as st

from frontend.enterprise_ai_frontend.models import ActivityItem, ChatMessage


def response_notices(message: ChatMessage) -> tuple[str, ...]:
    notices: list[str] = []
    if message.deterministic_fallback_used:
        notices.append("A deterministic fallback response was used.")
    if message.deterministic_analysis_rendering_used:
        notices.append("Verified structured analysis was rendered deterministically.")
    return tuple(notices)


def render_message(message: ChatMessage) -> None:
    with st.chat_message(message.role):
        st.markdown(message.content)
        if message.completion_status is not None:
            st.caption(f"Completion: {message.completion_status.value.replace('_', ' ')}")
        if message.selected_route is not None:
            st.caption(f"Route: {message.selected_route.value}")
        if message.insufficient_evidence:
            st.warning("The available authorized evidence was insufficient.")
        for notice in response_notices(message):
            st.info(notice)
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
        if message.analysis_result is not None:
            result = message.analysis_result
            with st.expander("Analysis provenance", expanded=False):
                st.write(f"Operation: `{result.operation.value}`")
                st.write(f"Authorized rows considered: {result.row_count_considered}")
                st.write(f"Rows excluded: {result.row_count_excluded}")
                st.write(f"Algorithm version: `{result.provenance.algorithm_version}`")
                if result.provenance.taxonomy_version is not None:
                    st.write(f"Taxonomy version: `{result.provenance.taxonomy_version}`")
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
