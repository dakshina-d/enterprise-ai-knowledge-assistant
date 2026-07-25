"""Create an ignored local authenticated-demo environment without printing secrets."""

from __future__ import annotations

import argparse
import os
import secrets
from getpass import getpass
from pathlib import Path
from typing import Literal

from enterprise_ai.security.password import PasswordService

MINIMUM_PASSWORD_LENGTH = 12


def _password_for(role: str, passwords: PasswordService) -> str:
    first = getpass(f"{role} demonstration password: ")
    second = getpass(f"Confirm {role.casefold()} password: ")
    if first != second:
        raise SystemExit(f"{role} passwords do not match; no file was written.")
    if len(first) < MINIMUM_PASSWORD_LENGTH:
        raise SystemExit(
            f"{role} password must contain at least {MINIMUM_PASSWORD_LENGTH} characters."
        )
    return passwords.hash_password(first)


def create_demo_environment(
    destination: Path,
    *,
    force: bool,
    llm_provider: Literal["fake", "ollama"],
) -> None:
    resolved = destination.resolve()
    if resolved.exists() and not force:
        raise SystemExit(f"{destination} already exists; use --force to replace it deliberately.")

    password_service = PasswordService()
    viewer_hash = _password_for("Viewer", password_service)
    analyst_hash = _password_for("Analyst", password_service)
    administrator_hash = _password_for("Administrator", password_service)
    provider_lines = (
        (
            "LLM_ENABLED=true",
            "LLM_PROVIDER=ollama",
            "OLLAMA_BASE_URL=http://127.0.0.1:11434",
            "OLLAMA_MODEL=qwen3:4b-instruct",
            "OLLAMA_REQUEST_TIMEOUT_SECONDS=120",
            "OLLAMA_NUM_CTX=8192",
            "OLLAMA_NUM_PREDICT=256",
            "OLLAMA_TEMPERATURE=0",
            "OLLAMA_KEEP_ALIVE=5m",
            "LLM_MAX_EVIDENCE_ITEMS=1",
            "LLM_MAX_EVIDENCE_CHARACTERS=2000",
            "LLM_MAX_EVIDENCE_ITEM_CHARACTERS=2000",
            "LLM_MAX_PROMPT_CHARACTERS=4000",
            "GRAPH_TIMEOUT_SECONDS=300",
            "RESEARCH_MAX_EXECUTION_SECONDS=90",
            "FRONTEND_STREAM_TIMEOUT_SECONDS=360",
        )
        if llm_provider == "ollama"
        else ("LLM_ENABLED=true", "LLM_PROVIDER=fake")
    )
    content = "\n".join(
        (
            "# Local assessment configuration. Never commit or share this file.",
            "AUTH_ENABLED=true",
            f"AUTH_TOKEN_SECRET={secrets.token_urlsafe(48)}",
            "DEMO_VIEWER_USERNAME=demo-viewer",
            f"DEMO_VIEWER_PASSWORD_HASH={viewer_hash}",
            "DEMO_ANALYST_USERNAME=demo-analyst",
            f"DEMO_ANALYST_PASSWORD_HASH={analyst_hash}",
            "DEMO_ADMIN_USERNAME=demo-admin",
            f"DEMO_ADMIN_PASSWORD_HASH={administrator_hash}",
            *provider_lines,
            "PINECONE_ENABLED=false",
            "RETRIEVAL_MODE=sparse",
            "LANGSMITH_TRACING=false",
            "",
        )
    )
    resolved.write_text(content, encoding="utf-8", newline="\n")
    try:
        os.chmod(resolved, 0o600)
    except OSError:
        pass
    print(f"Created local assessment configuration at {destination}.")
    print("Secrets and password hashes were written to the file and were not displayed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".env.demo"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--llm-provider",
        choices=("fake", "ollama"),
        default="fake",
        help="Write safe deterministic fake settings or local Ollama/Qwen settings.",
    )
    arguments = parser.parse_args()
    create_demo_environment(
        arguments.output,
        force=arguments.force,
        llm_provider=arguments.llm_provider,
    )


if __name__ == "__main__":
    main()
