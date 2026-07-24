"""Create an ignored local authenticated-demo environment without printing secrets."""

from __future__ import annotations

import argparse
import os
import secrets
from getpass import getpass
from pathlib import Path

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


def create_demo_environment(destination: Path, *, force: bool) -> None:
    resolved = destination.resolve()
    if resolved.exists() and not force:
        raise SystemExit(f"{destination} already exists; use --force to replace it deliberately.")

    password_service = PasswordService()
    viewer_hash = _password_for("Viewer", password_service)
    analyst_hash = _password_for("Analyst", password_service)
    administrator_hash = _password_for("Administrator", password_service)
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
            "LLM_ENABLED=true",
            "LLM_PROVIDER=fake",
            "PINECONE_ENABLED=false",
            "GRAPH_OFFLINE_RETRIEVAL_MODE=sparse",
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
    arguments = parser.parse_args()
    create_demo_environment(arguments.output, force=arguments.force)


if __name__ == "__main__":
    main()
