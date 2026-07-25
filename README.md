# Enterprise AI Knowledge Assistant

[![Repository CI](https://github.com/dakshina-d/enterprise-ai-knowledge-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/dakshina-d/enterprise-ai-knowledge-assistant/actions/workflows/ci.yml)

A bounded executable assessment PoC for authorization-aware enterprise knowledge retrieval,
recursive research, typed analysis, and read-only enterprise-data tools.

The repository uses a deterministic 51-document corpus for the fictional Lanka Horizon Commercial
Bank. It contains no real customer, employee, bank, or production data and is not presented as a
production-ready system.

## Assessment status

Mandatory assessment capabilities are executable and covered by offline tests: Streamlit chat and
real-time workflow and Agent Activity streaming through SSE, FastAPI JSON/SSE,
LangGraph Supervisor/Retrieval/Research/Response agents, bounded
recursive research, local BM25 and optional Pinecone dense/hybrid retrieval, session memory,
restricted analysis, local read-only MCP tools, grounded citations, RBAC, Token Bucket limits,
guardrails, structured logging, safe tracing, and graceful dependency failures.

The final requirement-by-requirement evidence is in the
[compliance audit](docs/assessment-compliance-audit.md). HITL, reranking, durable/long-term memory,
persistent feedback, arbitrary Python, remote MCP OAuth, durable replay, and enterprise IdP
integration are deliberately unimplemented.

## Architecture

[![Final assessment architecture](docs/assets/final-architecture.svg)](docs/final-architecture.md)

FastAPI is the non-bypassable policy boundary. Browser and model inputs cannot supply identity,
permissions, routes, tools, namespaces, filters, or authorization policy. Retrieved documents are
untrusted data and are reauthorized and validated before model context and citation completion.
Memory, checkpoints, rate-limit buckets, restricted analysis, and MCP execution are process-local
PoC boundaries.

See the [renderable Mermaid source and trust-boundary notes](docs/final-architecture.md).

## Key capabilities

- Authenticated multi-turn Streamlit chat using incremental native POST SSE.
- Live Agent Activity Panel with safe node, retrieval, research, tool, validation, and memory events.
- Typed LangGraph state and deterministic role/intent routing.
- Simple retrieval and bounded recursive multi-document research.
- Runtime-selectable local BM25 sparse retrieval or Pinecone dense+BM25 hybrid retrieval,
  namespace/metadata filters, attribution, and local post-query authorization rechecks.
- Three official-SDK local read-only MCP tools and typed restricted incident analysis.
- Native local Ollama/Qwen, fake/offline, and optional OpenAI Responses providers with grounded
  structured output, citation validation, response guardrails, timeout handling, and deterministic
  fallback.
- Privacy-safe optional LangSmith hierarchy and structured HTTP/graph logs.

## Security model

- Local assessment authentication uses Argon2id password hashes and pinned HS256 JWT validation.
- Viewer, Analyst, and Administrator receive only explicitly defined backend permissions.
- Every retrieval result and tool request is rechecked at the backend boundary.
- Strict API schemas reject client-supplied role, permission, route, tool, namespace, or policy.
- Direct prompt attacks and instruction-bearing retrieved evidence cannot alter graph/tool policy.
- Restricted analysis accepts typed allowlisted operations, never caller-supplied Python.
- Logs, traces, events, UI activity, and safe errors exclude raw prompts, evidence, credentials,
  private reasoning, provider errors, and internal paths.

This authentication model is for local demonstration only. Production requires organizational
OIDC, MFA, revocation, managed keys, distributed authorization context, and operational controls.
See [security design](docs/security-design.md).

## Quick start

Prerequisites: Python 3.12, `pip`, and optionally Docker Compose v2.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python scripts/create_demo_env.py --llm-provider ollama
python -m enterprise_ai.llm.cli check-ollama
```

The last command securely prompts for Viewer/Analyst/Administrator passwords and writes the ignored
`.env.demo`. It never prints the passwords, signing secret, or Argon2 hashes.

## Native local startup

Load `.env.demo` into the API terminal without displaying it:

```powershell
Get-Content .env.demo | ForEach-Object {
    if ($_ -and -not $_.StartsWith('#')) {
        $name, $value = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

uvicorn enterprise_ai.main:app --factory --host 127.0.0.1 --port 8000
```

In a second activated terminal:

```powershell
$env:FRONTEND_API_BASE_URL='http://127.0.0.1:8000'
streamlit run frontend/streamlit_app.py --server.address=127.0.0.1 --server.port=8501
```

Open:

- Streamlit: `http://127.0.0.1:8501`
- API documentation: `http://127.0.0.1:8000/docs`
- Liveness: `http://127.0.0.1:8000/health/live`
- Readiness: `http://127.0.0.1:8000/health/ready`

Do not use reload mode for the recorded assessment. Detailed native environment and shutdown
instructions are in [local and container deployment](docs/local-container-deployment.md).

### Optional Pinecone hybrid startup

Sparse mode is the credential-free default: `RETRIEVAL_MODE=sparse`. To use Pinecone for actual
FastAPI chat, bootstrap and verify the existing configured index first, then start the API with both
Pinecone and hybrid runtime selection enabled:

```powershell
$env:PINECONE_API_KEY='<SET_LOCALLY>'
$env:PINECONE_ENABLED='true'
$env:RETRIEVAL_MODE='pinecone_hybrid'
$env:PINECONE_INDEX_NAME='lhcb-knowledge-dev'
$env:PINECONE_NAMESPACE='lhcb-knowledge-dev-v1'

python -m enterprise_ai.retrieval.cli bootstrap-index
python -m enterprise_ai.retrieval.cli index
python -m enterprise_ai.retrieval.cli check-index
uvicorn enterprise_ai.main:app --factory --host 127.0.0.1 --port 8000
```

Do not place a real key in source, `.env.example`, terminal output, screenshots, or the recording.
The complete Viewer/Admin/RBAC live-check and restoration procedure is in the
[demonstration runbook](docs/demo-runbook.md).

## Docker Compose startup

The stack uses one secure Python 3.12 image and separate `api` and `ui` services. Both run non-root
with read-only root filesystems, dropped capabilities, `no-new-privileges`, bounded temporary
storage, Python health checks, and loopback-only host ports.

Infrastructure smoke mode uses fake/offline providers and leaves authentication disabled. It proves
startup and health only; interactive Streamlit login requires authenticated mode.

```powershell
docker compose config --quiet
docker compose build
docker compose up -d
python scripts/container_smoke.py
docker compose ps
docker compose down --remove-orphans
```

Authenticated demo mode:

```powershell
python scripts/create_demo_env.py --llm-provider ollama
docker compose --env-file .env.demo up -d --build
python scripts/container_smoke.py
```

Stop and remove it:

```powershell
docker compose --env-file .env.demo down --remove-orphans
Remove-Item -LiteralPath .env.demo
```

The API container reaches host Ollama at `http://host.docker.internal:11434`; Compose neither
starts Ollama nor downloads or embeds the model. OpenAI, Pinecone, and LangSmith remain disabled
unless explicitly configured. Pinecone chat also requires `RETRIEVAL_MODE=pinecone_hybrid`.
The implemented MCP path remains local/in-process; Compose does not
invent a remote MCP service.

## Demo users and example questions

Usernames default to `demo-viewer`, `demo-analyst`, and `demo-admin`; passwords are the private
values entered into `create_demo_env.py`.

| Role | Exact example | Expected route/outcome |
|---|---|---|
| Viewer | `What does the active Payment Queue Backlog Recovery Runbook require for controlled backlog drain and idempotency verification?` | `simple_retrieval`, grounded citations |
| Viewer | `Explain that again.` | multi-turn context continuation |
| Viewer | `Count payment incidents by root cause.` | denied before Python analysis |
| Viewer | `Who owns the payment-gateway service?` | denied before MCP |
| Viewer | `Show the restricted disaster-recovery topology.` | denied with no restricted evidence |
| Analyst | `Who owns the payment-gateway service?` | `mcp_tool`, safe provenance |
| Analyst | `Count payment incidents by root cause.` | `python_analysis`, typed result |
| Analyst | `Compare pending payment status in September and delayed settlement in February.` | `recursive_research`, bounded fan-out and citations |
| Administrator | `What does INC-PAY-2025-126 say about certificate lifecycle ownership?` | authorized restricted retrieval |

The main local recording uses Ollama with `qwen3:4b-instruct` and local sparse retrieval. Fake
remains the deterministic CI/infrastructure-smoke provider; OpenAI remains an optional adapter.

| Environment | LLM |
|---|---|
| CI/tests | `FakeLLMProvider` |
| Local assessment | Ollama + `qwen3:4b-instruct` |
| Optional cloud | OpenAI Responses API (`store=false`) |

Qwen is pretrained and is not trained on this corpus. Enterprise documents are indexed for RAG;
document updates require re-ingestion and re-indexing, not model retraining.

## Testing and deterministic verification

```powershell
python -m pytest -q --basetemp=.pytest-final-tmp/full

python -m ruff format --check .
python -m ruff check .
python -m mypy backend/src frontend ingestion/src scripts

python scripts/generate_sample_documents.py --check
python scripts/validate_sample_documents.py
python -m enterprise_ai_ingestion check
python -m enterprise_ai_ingestion validate
python -m enterprise_ai.retrieval.cli check-sparse
python -m enterprise_ai.retrieval.cli validate-sparse
python -m enterprise_ai.research.cli evaluate
python -m enterprise_ai.graph.cli trace-demo --query hello
python -m enterprise_ai.mcp_tools.cli list-tools
python scripts/check_documentation_links.py
docker compose config --quiet
```

GitHub Actions runs deterministic Python 3.12 validation without OpenAI, Pinecone, LangSmith, or
remote MCP credentials. It never uses `pull_request_target`, has read-only repository permission,
and checks that verification does not mutate tracked files.

## LangSmith tracing

Tracing is disabled by default. The application exports allowlisted identifiers, counts, roles,
routes, statuses, hierarchy, and outcome flags—not questions, prompts, evidence, drafts, secrets,
private reasoning, or raw exceptions.

Offline verification:

```powershell
python -m enterprise_ai.graph.cli trace-demo --query hello
```

For the manual trace demonstration, privately set
`LANGSMITH_API_KEY='<SET_LOCALLY>'`, `LANGSMITH_TRACING=true`, and
`LANGSMITH_PROJECT=enterprise-ai-knowledge-assistant-dev`. Hide private
trace URLs/identifiers during recording and revoke the key afterward. See
[LangSmith tracing design](docs/langsmith-tracing-design.md) and the
[demo runbook](docs/demo-runbook.md).

## Assignment evidence

- [Final architecture](docs/final-architecture.md)
- [Assessment compliance audit](docs/assessment-compliance-audit.md)
- [Requirements traceability](docs/requirements-traceability.md)
- [Model selection rationale](docs/model-selection.md)
- [Assumptions and trade-offs](docs/assumptions-and-tradeoffs.md)
- [45-minute demonstration script](docs/demo-script-45-minutes.md)
- [Demonstration runbook](docs/demo-runbook.md)
- [Demonstration evidence checklist](docs/demo-evidence-checklist.md)
- [Final submission checklist](docs/final-submission-checklist.md)
- [Submission document](docs/submission.md)
- [Local/container deployment](docs/local-container-deployment.md)

The public video URL and final commit SHA remain manual post-commit fields and are never invented.

## Assumptions and limitations

The architectural choices and production gaps are explained in
[assumptions and trade-offs](docs/assumptions-and-tradeoffs.md). Principal limitations:

- local assessment authentication, not enterprise OIDC;
- process-local memory, checkpoints, session ownership, and Token Bucket;
- no durable SSE replay or distributed workers;
- local read-only MCP without remote OAuth;
- typed aggregate analysis rather than arbitrary Python;
- fake provider for CI, explicit local Ollama/Qwen for assessment, and optional cloud credentials;
- structural citations/guardrails rather than universal semantic or safety proof;
- no HITL, reranking, durable long-term memory, or persistent feedback; and
- no production secrets, networking, telemetry, retention, governance, or scaling platform.

## Repository structure

```text
backend/        FastAPI, LangGraph, retrieval, agents, tools, security, tracing, and tests
frontend/       Streamlit presentation, SSE client, state, rendering, activity, and tests
ingestion/      Offline deterministic parsing/chunking and artifact validation
mcp_server/     MCP protocol tests and package boundary
data/           Synthetic corpus, committed retrieval artifacts, evaluation, security fixtures
docs/           Architecture, design, audit, demo, deployment, and submission evidence
scripts/        Corpus, password/demo-env, smoke, and documentation-link utilities
Dockerfile      Shared non-root Python application image
compose.yaml    Local API/UI proof-of-concept stack
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.
