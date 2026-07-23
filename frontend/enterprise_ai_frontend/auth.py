"""Streamlit authentication view and safe login transition."""

from typing import cast

import streamlit as st

from frontend.enterprise_ai_frontend.api_client import APIClient
from frontend.enterprise_ai_frontend.errors import FrontendError
from frontend.enterprise_ai_frontend.state import StateStore, authenticate


def render_login(client: APIClient) -> None:
    st.title("Enterprise AI Knowledge Assistant")
    st.caption("Sign in with your authorized enterprise account.")
    with st.form("login-form", clear_on_submit=False):
        username = st.text_input("Username", max_chars=128)
        password = st.text_input("Password", type="password", max_chars=1_024)
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if not submitted:
        return
    if not username.strip() or not password:
        st.error("Enter your username and password.")
        return
    with st.spinner("Signing in..."):
        try:
            login = client.login(username.strip(), password)
        except FrontendError as error:
            st.error(error.public_message)
            return
    authenticate(cast(StateStore, st.session_state), login)
    st.rerun()
