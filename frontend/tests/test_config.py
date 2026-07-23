"""Frontend configuration validation."""

import pytest
from pydantic import ValidationError

from frontend.enterprise_ai_frontend.config import FrontendSettings


def test_default_and_custom_api_origins() -> None:
    assert str(FrontendSettings().api_base_url) == "http://127.0.0.1:8000/"
    custom = FrontendSettings.model_validate({"api_base_url": "https://assistant.example.test"})
    assert custom.endpoint("/api/v1/chat") == "https://assistant.example.test/api/v1/chat"


@pytest.mark.parametrize(
    "value",
    [
        "file:///tmp/socket",
        "https://user:password@example.test",
        "https://example.test/path",
        "https://example.test?token=value",
    ],
)
def test_unsafe_or_malformed_api_origins_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        FrontendSettings.model_validate({"api_base_url": value})


def test_configuration_representation_contains_no_secret_fields() -> None:
    representation = repr(FrontendSettings())
    assert "password" not in representation.casefold()
    assert "token" not in representation.casefold()
