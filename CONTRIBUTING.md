# Contributing

Use Python 3.12 and create focused commits. Keep implementation status honest: proposed capabilities must remain labeled as planned until they are executable and verified.

## Workflow

1. Create and activate a virtual environment.
2. Install development dependencies with `python -m pip install -e ".[dev]"`.
3. Add type hints and tests for changed behavior.
4. Run `ruff format .`, `ruff check .`, `mypy backend/src frontend`, and `pytest`.
5. Update the traceability matrix and architecture documentation when scope changes.

Never add credentials, sensitive organizational data, generated environment files, or unrestricted execution paths. Prefer small modules with explicit boundaries and dependency injection at integration seams.

## Repository review checklist

Before proposing a commit:

1. Run the full test, formatting, lint, type-check, corpus-integrity, and documentation-link gates
   documented in the README.
2. Confirm `docker compose config --quiet` succeeds when deployment files change.
3. Check that credentials, generated environment files, model weights, caches, logs, and local
   runtime artifacts are not tracked.
4. Confirm `data/processed` has no unintended changes or deletions.
5. Review `git status --short`, `git diff --check`, and the final diff for unrelated changes.
6. Verify CI is green and repository links are accessible when those external checks apply.
