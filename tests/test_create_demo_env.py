"""Safe local demo-environment generation tests."""

from pathlib import Path

import pytest
from enterprise_ai.core.config import Settings
from enterprise_ai.main import create_app
from enterprise_ai.retrieval.config import RetrievalSettings
from fastapi.testclient import TestClient

from scripts import create_demo_env


def _generated_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, separator, value = line.partition("=")
            assert separator and name
            values[name] = value
    return values


@pytest.mark.parametrize("provider", ["fake", "ollama"])
def test_demo_environment_writes_selected_provider_without_printing_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: str,
) -> None:
    monkeypatch.setattr(create_demo_env, "_password_for", lambda *_args: "test-hash")
    destination = tmp_path / ".env.demo"

    create_demo_env.create_demo_environment(
        destination,
        force=False,
        llm_provider=provider,  # type: ignore[arg-type]
    )

    content = destination.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert f"LLM_PROVIDER={provider}" in content
    assert "RETRIEVAL_MODE=sparse" in content
    assert "test-hash" in content
    assert "test-hash" not in output
    assert "AUTH_TOKEN_SECRET=" in content
    assert "AUTH_TOKEN_SECRET=" not in output
    if provider == "ollama":
        assert "OLLAMA_MODEL=qwen3:4b-instruct" in content
        assert "OLLAMA_BASE_URL=http://127.0.0.1:11434" in content
        assert "GRAPH_TIMEOUT_SECONDS=300" in content
    else:
        assert "OLLAMA_MODEL=" not in content


def test_demo_environment_refuses_overwrite_before_prompting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / ".env.demo"
    destination.write_text("owner-content", encoding="utf-8")
    monkeypatch.setattr(
        create_demo_env,
        "_password_for",
        lambda *_args: pytest.fail("password prompt must not run"),
    )

    with pytest.raises(SystemExit, match="--force"):
        create_demo_env.create_demo_environment(
            destination,
            force=False,
            llm_provider="ollama",
        )

    assert destination.read_text(encoding="utf-8") == "owner-content"


def test_generated_ollama_environment_constructs_settings_and_application_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(create_demo_env, "_password_for", lambda *_args: "test-hash")
    destination = tmp_path / ".env.demo"
    create_demo_env.create_demo_environment(
        destination,
        force=False,
        llm_provider="ollama",
    )

    generated = _generated_environment(destination)
    for name in generated:
        monkeypatch.delenv(name, raising=False)

    retrieval_settings = RetrievalSettings(_env_file=destination)
    assert retrieval_settings.llm_provider == "ollama"
    assert retrieval_settings.retrieval_mode == "sparse"
    assert retrieval_settings.ollama_temperature == 0.0
    assert isinstance(retrieval_settings.ollama_temperature, float)

    for name, value in generated.items():
        monkeypatch.setenv(name, value)

    application_settings = Settings(_env_file=None)
    with TestClient(create_app(application_settings)) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
