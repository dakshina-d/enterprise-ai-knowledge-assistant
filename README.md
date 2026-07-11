# Enterprise AI Knowledge Assistant

An enterprise-grade technical-assessment foundation for a future conversational knowledge assistant.

## Current status

Implemented: modular repository scaffolding, reusable validated domain/API contracts, proof-of-concept authentication, deterministic RBAC and rate limiting, health endpoints, a deterministic 51-document synthetic corpus, offline ingestion, and optional Pinecone dense indexing/retrieval with offline-tested security filters.

Implemented retrieval now includes local BM25 sparse search and transparent weighted dense–sparse hybrid fusion. Planned—not implemented: reranking, LangGraph agents, LLM answer generation, MCP/Python tool execution, conversational memory, streaming, guardrails, and business workflows.

The repository includes a deterministic 51-document synthetic corpus for the fictional Lanka Horizon Commercial Bank. All people, incidents, systems, dates, metrics, and identifiers are synthetic and do not describe any real financial institution.

## Proposed architecture

The planned system separates the Streamlit experience, FastAPI orchestration API, ingestion pipeline, and constrained MCP server. Future backend modules reserve boundaries for agents, graph orchestration, hybrid retrieval, tools, memory, security, observability, models, and services. See [docs/architecture.md](docs/architecture.md).

Pinecone is disabled by default and never runs during API startup. After configuring `.env`, use the explicit `enterprise_ai.retrieval.cli` bootstrap, index, check, query, and evaluation commands documented in [dense retrieval design](docs/dense-retrieval-design.md).

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

## Proof-of-concept authentication

Authentication is disabled by default. To enable it, generate one Argon2id hash per demonstration user without echoing the password:

```bash
python scripts/generate_password_hash.py
```

Place only the resulting hashes and a random signing secret of at least 32 characters in a local `.env` using the variables shown in `.env.example`; never commit that file. Set `AUTH_ENABLED=true`, then use `POST /api/v1/auth/login` to obtain an HS256 bearer access token and `GET /api/v1/auth/me` to inspect the safe authenticated profile. Usernames are normalized by trimming surrounding whitespace and applying Unicode case-folding.

The configured viewer, analyst, and administrator users are assessment-only. There are no refresh tokens, revocation, account lockout, MFA, federation, or distributed session controls. Production must replace demonstration authentication and local JWT issuance with an organizational OIDC identity provider such as Microsoft Entra ID, Keycloak, or Auth0, while retaining backend authorization checks.

## Proof-of-concept rate limiting

Rate limiting is enabled by default; set `RATE_LIMIT_ENABLED=false` only as an explicit local/test choice. Login uses an anonymous network fingerprint bucket (capacity 5, refill 1/30 token per second, cost 1); `/api/v1/auth/me` uses a backend-derived user-ID bucket (capacity 30, refill 0.5 token per second, cost 1). An expensive policy contract (capacity 10, refill 1/15 token per second, cost 2) is reserved for future AI/tool routes and is not attached today.

Allowed responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset`; reset is seconds until the current request cost is available and is `0` when allowed. Denials return `429`, the same informational headers, and `Retry-After` in whole seconds. Health endpoints remain unthrottled for orchestrator probes.

The in-memory limiter is concurrency-safe only within one process, resets on restart, and does not coordinate workers. Production requires a shared Redis-compatible implementation using an atomic Lua script or transaction. Proxy headers are ignored by default; enable them only behind an explicitly allowlisted single-hop proxy.

## Quality checks

```bash
ruff format --check .
ruff check .
mypy backend/src frontend
pytest
pre-commit run --all-files
```

## Sample corpus

```bash
py -3.12 scripts/generate_sample_documents.py
py -3.12 scripts/generate_sample_documents.py --check
py -3.12 scripts/validate_sample_documents.py
```

The valid Markdown corpus and body-hash manifest are under `data/sample_documents/`. Research/access benchmarks are under `data/evaluation/`. Malicious-test-only fixtures are isolated under `data/security_fixtures/` and excluded from the valid manifest. See [sample-data design](docs/sample-data-design.md).

Build or verify deterministic retrieval-ready artifacts with:

```bash
py -3.12 -m enterprise_ai_ingestion build
py -3.12 -m enterprise_ai_ingestion check
py -3.12 -m enterprise_ai_ingestion validate
```

The commands are offline and provider-neutral. See [ingestion design](docs/ingestion-design.md) for safety boundaries, artifact contracts, and limitations.

## Baseline LangGraph orchestration

The repository now includes a real LangGraph 1.x asynchronous baseline with typed state and
input/output contracts, deterministic intent and role-aware routing, offline BM25 retrieval,
validated evidence, sanitized activity events, bounded execution, and an injected in-memory
checkpointer. Inspect or exercise it without API keys or network access:

```bash
py -3.12 -m enterprise_ai.graph.cli describe
py -3.12 -m enterprise_ai.graph.cli run "hello" --role viewer
py -3.12 -m enterprise_ai.graph.cli stream "hello" --role viewer
py -3.12 -m enterprise_ai.graph.cli run "What is the leave policy?" --role viewer --top-k 3
```

The CLI role controls backend authorization; it does not bypass document access rules. The local
checkpointer is volatile, process-local assessment infrastructure. See
[graph design](docs/graph-design.md) for topology, security boundaries, production replacement,
and the deliberately unsupported future nodes.

Bounded session conversational memory is available within one running CLI/runtime process. It
stores sanitized turns and authorized attribution—not evidence bodies—and supports conservative
follow-ups with owner/role isolation. It is lost on restart and is not shared across workers. See
[session-memory design](docs/session-memory-design.md) and the `conversation` CLI command.

Restricted structured Python analysis is available to policy-authorized analysts and
administrators. It executes only typed allowlisted aggregate operations over authorized committed
incident rows—never caller-supplied Python. See
[python-analysis design](docs/python-analysis-tool-design.md).

## Environment configuration

Configuration is loaded from environment variables by `enterprise_ai.core.config.Settings`. Application settings include `APP_ENV`, `LOG_LEVEL`, `API_HOST`, `API_PORT`, and the documented `AUTH_*`/`DEMO_*` proof-of-concept variables. Future provider variable names are listed in `.env.example`; no provider integration is active.

Never commit `.env`, API keys, credentials, or production configuration. Use a secrets manager in deployed environments and rotate any credential that is accidentally exposed.

## Repository structure

```text
backend/      FastAPI application and backend tests
frontend/     Streamlit presentation layer
ingestion/    Offline deterministic parsing and chunking component
mcp_server/   Reserved constrained MCP component
data/         Non-sensitive sample documents
docs/         Architecture, security, decisions, and assessment evidence
scripts/      Automation entry points
tests/        Reserved cross-component tests
```

## Current limitations

The health responses are static process-level placeholders and do not check dependencies. The
Streamlit UI does not call the backend and chat is disabled. Dense and sparse retrieval plus the
baseline orchestration can be exercised from their CLIs, but there is no LLM response synthesis,
recursive research execution, durable memory, observability provider, browser streaming endpoint,
Python sandbox, MCP execution, or human approval workflow yet.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and [requirements traceability](docs/requirements-traceability.md) for implementation status.
