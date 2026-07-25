# Assessment Requirements Traceability

Runtime code and executable tests are the source of truth. “Credential-dependent verification”
means the implementation and offline contracts exist, but current live-provider evidence still
requires a reviewer-supplied temporary credential. Risk is the remaining submission risk, not a
claim of production readiness.

| Requirement | Implementation | Tests | Demo evidence | Status | Risk |
|---|---|---|---|---|---|
| Python and readable typed code | `backend/src`, `frontend`, `ingestion/src`, `scripts`; Ruff and strict MyPy configuration in `pyproject.toml` | Full Pytest, Ruff, MyPy | Show repository structure and quality output | Implemented | Low — final CI must remain green |
| Async FastAPI JSON and SSE API | `enterprise_ai.main`, `api/chat.py`, `api/sse.py`, `graph/runtime.py` | `test_chat_api.py`, `test_chat_sse.py`, SSE cancellation/keepalive suites | `/health/live`, `/health/ready`, authenticated JSON/SSE turn | Implemented | Low — process-local runtime |
| Streamlit multi-turn chat and Agent Activity | `frontend/enterprise_ai_frontend`, `frontend/streamlit_app.py` | `frontend/tests/test_integration_flows.py`, `test_streamlit_app.py`, `test_sse.py` | Viewer query, follow-up, incremental activity, citations | Implemented | Low — no durable replay |
| LangGraph workflow and supervisor routing | `graph/builder.py`, `nodes.py`, `routing.py`, typed `GraphState` | graph topology/routing/baseline and role-acceptance suites | Route events for retrieval, research, analysis, MCP, deny | Implemented | Low — deterministic PoC router |
| Security-denial and exact-identifier precedence | `graph/routing.py`, `security/guardrails.py`, `retrieval/identifiers.py` | routing, exact-identifier, security acceptance suites | Secret-exfiltration denial and known/unknown incident queries | Implemented | Low — pattern controls are bounded |
| Retrieval capability and source attribution | `graph/nodes.py`, `retrieval`, `GraphEvidenceAttribution`, citation validator | sparse/dense/hybrid, grounding, citation and role suites | Viewer runbook answer with exact source/lines | Implemented | Low — governed synthetic corpus |
| Offline BM25 sparse retrieval | `retrieval/sparse`, `OfflineSparseAdapter`; `RETRIEVAL_MODE=sparse` | `test_sparse_hybrid.py`, CLI check/validate/evaluate | Credential-free default query and sparse CLI checks | Implemented | Low — lexical recall limitations |
| Pinecone dense/hybrid FastAPI runtime | `api/runtime.py:create_api_retriever`, `DenseRetrievalService`, `HybridRetrievalService`, `PineconeSdkGateway`; `RETRIEVAL_MODE=pinecone_hybrid` | `test_runtime_retrieval.py`, `test_dense_retrieval.py`, `test_sparse_hybrid.py` | Live bootstrap/index/check plus Viewer/Admin queries in `demo-runbook.md` | Credential-dependent verification | High — temporary key and live index check still required |
| Namespace, fingerprint, metadata and RBAC filters | `retrieval/config.py`, `filters.py`, `metadata.py`, `dense_retriever.py`, `indexer.py` | dense namespace/filter/fingerprint/exact-ID/unauthorized-result tests | Show configured namespace and safe check-index counts/fingerprint | Implemented | Low — one configured namespace |
| Hybrid fusion | `retrieval/hybrid/retriever.py`, `fusion.py`; dense and sparse branches run concurrently | hybrid fusion/partial/cancellation tests | Live hybrid result modes and offline deterministic tests | Implemented | Low — weights are configuration, not learned |
| Recursive research/RLM concepts | `research` catalog, planner, worker graph, budgets, aggregation, coverage and conflicts | research unit/integration/evaluation suites | September-versus-February comparison with plan, workers, both sources and coverage | Implemented | Low — bounded typed recursion only |
| Python-based planning/search | deterministic Python catalog exploration, `FakeResearchPlanner`, plan validator and typed worker dispatch | planner, validator, worker, coverage and budget tests | Explain deterministic/Python planning and bounded child tasks | Implemented | Low — no unrestricted autonomous recursion |
| Restricted Python analysis | `tools/python_analysis`, backend authorization in graph node/service | Python tool, RBAC, tracing and failure-event suites | Root-cause counts, 8 included/8 excluded, authorization/tool events | Implemented | Low — typed aggregates, no arbitrary code |
| MCP enterprise-data tool | `mcp_tools` official SDK in-memory transport, three read-only allowlisted tools | MCP server/client/security/integration/failure suites | Payment-gateway ownership plus MCP provenance and no citations | Implemented | Low — local fictional service, no remote OAuth |
| Session memory | `memory` ownership, context resolution, bounded in-memory store | memory concurrency/ownership and role-acceptance follow-up tests | “Explain that again” in same Viewer conversation | Implemented | Low — process-local and non-durable |
| Local Qwen response generation | `OllamaChatProvider`, schema-constrained `GroundedResponseService`; `qwen3:4b-instruct` | mocked provider, privacy, follow-up, live opt-in tests | Ollama readiness then grounded retrieval turn | Implemented | Medium — CPU latency and local model availability |
| Grounding, citations and deterministic fallback | response service, evidence context, citation repair/validation, extractive fallback | grounding, citation, failure-matrix and acceptance suites | Grounded answer, one fallback, no unrelated substitution | Implemented | Low — quality depends on retrieval |
| LangSmith complete safe tracing | `observability/tracing.py`, graph/node/research/LLM/MCP spans and bounded shutdown flush | hierarchy, sanitization, concurrency, graph tracing, MCP and failure-matrix tests | Live root/children inspection steps in `demo-runbook.md` | Credential-dependent verification | High — fresh live dashboard evidence still required |
| Authentication and Viewer/Analyst/Admin RBAC | `security`, API dependencies, strict JWT/token/password settings | authentication, authorization, IDOR/session and role-acceptance suites | Login as all roles; denied and allowed tool/document flows | Implemented | Low — demo identities, not enterprise IdP |
| Non-bypassable tool/document authorization | `AuthorizationService` invoked before retrieval, MCP construction and analysis | negative RBAC/tool/filter/provider-result tests | Viewer denied before MCP/analysis and restricted exact record | Implemented | Low — local policy tables |
| Prompt injection, exfiltration and tool-abuse controls | `security/guardrails.py`, untrusted-content checks, safe selectors and output policy | assessment guardrails, security fixtures, MCP selector and citation tests | Secrets/configuration denial; no tools/retrieval/citations | Implemented | Low — deterministic bounded detection |
| Per-user token-bucket rate limiting | `rate_limit` policy/store/token bucket plus FastAPI dependencies | store, concurrency, cleanup and API 429 suites | Show configuration and automated 429 evidence | Implemented | Low — process-local buckets |
| Graceful failure handling | guarded nodes, typed retrieval/LLM/MCP/analysis errors, safe SSE terminals and event journal | failure matrix, chat SSE, MCP, retrieval, analysis event-preservation tests | LLM fallback and one `response.failed` application failure | Implemented | Low — no distributed circuit breaker |
| LangSmith/Pinecone secret safety | `SecretStr`, sanitized trace metadata, safe provider exception translation, ignored environment files | tracing config/sanitization and Pinecone public-failure tests | Set placeholders privately; show only configuration presence | Implemented | Low — operator must hide dashboards and shell history |
| Docker packaging | non-root `Dockerfile`; hardened API/UI `compose.yaml`; health checks; host Ollama configuration | Compose config, container smoke script and startup tests | Build, start, health, logs, restart and clean shutdown | Implemented | Medium — must re-run Docker Desktop lifecycle on final files |
| Architecture, assumptions and trade-offs | `docs/final-architecture.md`, `assumptions-and-tradeoffs.md`, design ADRs | documentation-link checker | Walk trust boundaries and implemented/optional components | Implemented | Low — keep diagram synchronized |
| Public repository and 45-minute demonstration | README, demo script/runbook, submission checklist/document | link checker and repository scans | Public video and incognito repository check | Partial | High — human recording, URL, final SHA and public-access check remain |

## Critical-gap disposition

The audit found one Critical implementation gap: FastAPI always constructed the offline sparse
adapter, leaving Pinecone hybrid reachable only from developer CLIs. `create_api_retriever()` now
selects sparse or Pinecone hybrid at the actual HTTP runtime boundary. No other mandatory component
was found absent from runtime. The final Docker lifecycle was verified locally. Live Pinecone, live
LangSmith, the public video, final commit SHA, and public-access checks remain explicit human
evidence tasks.

The broader design evidence remains in the
[assessment compliance audit](assessment-compliance-audit.md); this matrix is the concise
submission index.
