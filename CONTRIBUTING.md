# Contributing

Use Python 3.12 and create focused commits. Keep implementation status honest: proposed capabilities must remain labeled as planned until they are executable and verified.

## Workflow

1. Create and activate a virtual environment.
2. Install development dependencies with `python -m pip install -e ".[dev]"`.
3. Add type hints and tests for changed behavior.
4. Run `ruff format .`, `ruff check .`, `mypy backend/src frontend`, and `pytest`.
5. Update the traceability matrix and architecture documentation when scope changes.

Never add credentials, sensitive organizational data, generated environment files, or unrestricted execution paths. Prefer small modules with explicit boundaries and dependency injection at integration seams.
