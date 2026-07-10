# Enterprise AI Knowledge Assistant

An enterprise-grade technical-assessment foundation for a future conversational knowledge assistant. This initial milestone establishes project structure, engineering standards, documentation, and runnable health checks only.

## Current status

Implemented: modular repository scaffolding, a FastAPI application factory, live/readiness health endpoints, JSON logging foundations, environment-based settings, a Streamlit placeholder, tests, and quality tooling.

Planned—not implemented: LangGraph agents, LLM calls, Pinecone retrieval, MCP tools, authentication/RBAC, rate limiting, conversational memory, guardrails, and business workflows.

## Proposed architecture

The planned system separates the Streamlit experience, FastAPI orchestration API, ingestion pipeline, and constrained MCP server. Future backend modules reserve boundaries for agents, graph orchestration, hybrid retrieval, tools, memory, security, observability, models, and services. See [docs/architecture.md](docs/architecture.md).

## Prerequisites

- Python 3.12
- `pip` and `venv`

## Local setup

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Optionally copy `.env.example` to `.env` and customize safe local values.

## Run the applications

```bash
uvicorn enterprise_ai.main:app --factory --reload
streamlit run frontend/streamlit_app.py
```

FastAPI serves `GET /health/live` and `GET /health/ready`. Interactive API documentation is available at `/docs`.

## Quality checks

```bash
ruff format --check .
ruff check .
mypy backend/src frontend
pytest
pre-commit run --all-files
```

## Environment configuration

Configuration is loaded from environment variables by `enterprise_ai.core.config.Settings`. Application settings currently include `APP_ENV`, `LOG_LEVEL`, `API_HOST`, and `API_PORT`. Future provider variable names are listed in `.env.example`; no provider integration is active.

Never commit `.env`, API keys, credentials, or production configuration. Use a secrets manager in deployed environments and rotate any credential that is accidentally exposed.

## Repository structure

```text
backend/      FastAPI application and backend tests
frontend/     Streamlit presentation layer
ingestion/    Reserved ingestion component
mcp_server/   Reserved constrained MCP component
data/         Non-sensitive sample documents
docs/         Architecture, security, decisions, and assessment evidence
scripts/      Automation entry points
tests/        Reserved cross-component tests
```

## Current limitations

The health responses are static process-level placeholders and do not check dependencies. The Streamlit UI does not call the backend and chat is disabled. There are no AI, retrieval, identity, authorization, memory, observability-provider, or tool-execution features yet.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and [requirements traceability](docs/requirements-traceability.md) for implementation status.
