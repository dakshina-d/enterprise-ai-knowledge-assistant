"""Placeholder Streamlit interface for the future assistant."""

import streamlit as st

st.set_page_config(page_title="Enterprise AI Knowledge Assistant", layout="wide")
st.title("Enterprise AI Knowledge Assistant")
st.caption("Technical-assessment foundation")

chat_column, activity_column = st.columns([2, 1])

with chat_column:
    st.subheader("Conversation")
    st.info("Backend integration and conversational capabilities will be added later.")
    st.text_area(
        "Chat history",
        value="Chat is not available in the scaffolding milestone.",
        height=240,
        disabled=True,
    )
    st.chat_input("Ask a question (coming soon)", disabled=True)

with activity_column:
    st.subheader("Agent activity")
    st.container(border=True).write("No agents are running. Agent orchestration is planned.")
