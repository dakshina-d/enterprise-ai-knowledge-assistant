"""Strict transport-contract tests for chat requests."""

import pytest
from enterprise_ai.api.schemas import ChatRequest
from enterprise_ai.core.config import Settings
from pydantic import ValidationError


@pytest.mark.parametrize("message", ["", " ", "\n\t", "x" * 4_001])
def test_message_bounds_are_strict(message: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message=message)


@pytest.mark.parametrize(
    "injected",
    [
        {"role": "administrator"},
        {"permissions": ["mcp_tools"]},
        {"trace_id": "00000000-0000-0000-0000-000000000000"},
        {"internal_route": "mcp_tool"},
        {"tool_name": "get_service_profile"},
        {"namespace": "restricted"},
    ],
)
def test_security_owned_fields_cannot_be_injected(injected: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"message": "hello", **injected})


@pytest.mark.parametrize("top_k", [0, 101])
def test_top_k_is_bounded(top_k: int) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="hello", top_k=top_k)


def test_wildcard_or_empty_cors_origins_are_rejected() -> None:
    for origins in [(), ("*",), ("http://localhost:8501/",)]:
        with pytest.raises(ValidationError):
            Settings(api_allowed_origins=origins)
