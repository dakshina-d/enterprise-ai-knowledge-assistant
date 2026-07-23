# Requirements Traceability

Repository CI is implemented with Python 3.12, offline provider policy, generated-artifact drift
checks, Ruff, strict MyPy, complete Pytest/JUnit output, read-only permissions, and clean-tree gating.

Statuses are intentionally strict: **Implemented** means executable and verified now; **Designed** means a reviewable contract exists but no runtime feature; **Planned** means runtime work remains. Design evidence never substitutes for an operational demo.

| Requirement | Priority | Planned component / design reference | Verification method | Current status | Demo evidence |
|---|---|---|---|---|---|
| Repository scaffolding | Must | Modular monorepo; [ADR 0001](adr/0001-project-structure.md) | Tree and packaging review | Implemented | Current directory walkthrough |
| Architecture and implementation roadmap | Must | [Architecture](architecture.md), [roadmap](implementation-roadmap.md), ADRs | Cross-document terminology/link and Mermaid review | Designed | Document walkthrough only |
| Shared domain and API contracts | Must | `enterprise_ai.models`; [API contracts](api-contracts.md), [graph design](graph-design.md), [event design](event-stream-design.md) | Model validation, serialization, strict typing, and boundary unit tests | Implemented | Current schema/test walkthrough; no runtime feature claimed |
| Proof-of-concept authentication | Must | Backend API/security; [API contracts](api-contracts.md), [security design](security-design.md) | Argon2, JWT claim/signature, login, `/auth/me`, error-safety and configuration tests | Implemented | Configured demo login and safe principal response |
| Deterministic RBAC foundation | Must | Backend security; [ADR 0005](adr/0005-rbac-enforcement-boundary.md), [security design](security-design.md) | Exact role matrix, default-deny, token-escalation and endpoint-denial tests | Implemented | Policy tests and safe 403 response; no tool execution |
| Retrieval authorization policy | Must | Backend security; [dense retrieval design](dense-retrieval-design.md), [ADR 0005](adr/0005-rbac-enforcement-boundary.md) | Mandatory provider filter plus local access-level/role recheck tests | Implemented | Offline dense retrieval denial matrix; live execution optional |
| Offline document ingestion and chunking | Must | `enterprise_ai_ingestion`; [ingestion design](ingestion-design.md), [retrieval design](retrieval-design.md) | Unit/integration tests, deterministic rebuild/check, independent artifact validation | Implemented | 51 documents transformed into validated local JSONL artifacts; no embeddings/index |
| Health endpoints | Must | Backend API; [API contracts](api-contracts.md) | Automated `live` and `ready` tests plus startup smoke test | Implemented | Current endpoint responses |
| Logging foundations | Must | Backend core; [architecture](architecture.md), [error handling](error-handling-design.md) | Ruff/MyPy and JSON formatter test/inspection | Implemented | Current JSON formatter; request events pending |
| Streamlit chat | Must | Frontend; [API contracts](api-contracts.md), [roadmap](implementation-roadmap.md) | UI and end-to-end chat tests | Planned | Disabled placeholder only |
| Multi-turn conversation | Must | Graph/memory; [graph design](graph-design.md), [testing strategy](testing-strategy.md) | Session ownership and multi-turn integration test | Planned | Future scripted session replay |
| Streaming responses | Must | FastAPI/Streamlit; [event design](event-stream-design.md), [ADR 0004](adr/0004-server-sent-events.md) | SSE ordering, reconnect, redaction, terminal-event tests | Planned | Future sanitized SSE capture |
| Live agent activity | Must | Graph event projector/UI; [event design](event-stream-design.md) | Event ordering, redaction, and terminal tests | Partial | Sanitized graph/CLI activity is implemented; UI transport remains planned |
| FastAPI | Must | Backend; [API contracts](api-contracts.md) | OpenAPI/endpoint integration and startup tests | Planned | Health-only baseline currently runs |
| Async APIs | Must | Backend/graph; [architecture](architecture.md), [API contracts](api-contracts.md) | Concurrent request and cancellation tests | Planned | Future concurrency test report |
| Async retrieval | Must | Retrieval; [dense retrieval design](dense-retrieval-design.md) | Offline async provider, timeout, retry, cancellation, and query tests | Implemented | Fake-provider evidence; live execution requires credentials |
| Async tool execution | Must | Graph/tools; [graph design](graph-design.md) | Parallel tool, timeout, and isolation tests | Partial | MCP and restricted Python paths implemented; broader tools planned |
| Structured logging | Must | Observability; [error handling](error-handling-design.md), [testing strategy](testing-strategy.md) | Schema, correlation, redaction, failure capture tests | Planned | JSON foundation only |
| LangGraph | Must | `enterprise_ai.graph`; [graph design](graph-design.md), [ADR 0002](adr/0002-langgraph-as-orchestrator.md) | Graph compile, invariant, route, isolation, stream, and terminal-state tests | Implemented | Async baseline graph and offline CLI; advanced nodes explicitly unsupported |
| Session conversational memory | Must | `enterprise_ai.memory`; [session memory](session-memory-design.md) | Bounds, TTL, ownership, idempotency, sanitization, concurrency, context, and multi-turn tests | Implemented | Process-local only; durable/distributed and semantic memory remain planned |
| Restricted Python analysis | Must | `enterprise_ai.tools.python_analysis`; [tool design](python-analysis-tool-design.md) | RBAC, extraction, taxonomy, operations, limits, determinism, graph, and prohibited-code tests | Implemented | Structured operations only; arbitrary Python and general sandbox intentionally absent |
| Grounded LLM responses and citations | Must | `enterprise_ai.llm`; [response design](llm-response-agent-design.md) | Provider, prompt, grounding, citation, repair, fallback, graph, and security tests | Implemented | Fake provider is default; optional OpenAI live test deferred without credentials |
| Supervisor agent | Must | Graph/agents; [graph design](graph-design.md) | Table-driven intent/complexity routing tests | Planned | Future route event/trace |
| Retrieval agent | Must | Agents/retrieval; [graph design](graph-design.md), [retrieval design](retrieval-design.md) | Grounded retrieval workflow tests | Planned | Future attributed answer |
| Research agent | Must | `enterprise_ai.research`; [research design](recursive-research-design.md) | Send fan-out, reducer, budget and offline scenario tests | Implemented | Graph 1.2 |
| Response agent | Must | Agents/guardrails; [graph design](graph-design.md) | Grounding, citation, response-policy tests | Planned | Future validated response |
| RLM decomposition | Must | Recursive research; [graph design](graph-design.md) | Structured plan compiler tests | Implemented | Typed tasks, not chain-of-thought |
| Recursive sub-analysis | Must | Research graph; [ADR 0006](adr/0006-recursive-research-design.md) | Depth, task and atomic budget tests | Implemented | Restricted typed Python operations only |
| Hybrid dense and sparse retrieval | Must | Pinecone dense plus local BM25; [sparse/hybrid design](sparse-and-hybrid-retrieval-design.md), [ADR 0003](adr/0003-hybrid-retrieval-strategy.md) | Versioned sparse evaluation, normalization/fusion and authorization tests | Implemented | Offline sparse metrics; live hybrid requires credentials |
| Pinecone namespaces | Must | Retrieval/ingestion; [dense retrieval design](dense-retrieval-design.md) | Single configured corpus namespace and gateway tests | Implemented | Live index inspection optional |
| Metadata filtering | Must | Retrieval/RBAC; [dense retrieval design](dense-retrieval-design.md), [ADR 0005](adr/0005-rbac-enforcement-boundary.md) | Mandatory build/access/role filter plus post-query recheck tests | Implemented | Offline viewer/analyst/admin denial matrix |
| Document attribution | Must | Evidence models; [retrieval design](retrieval-design.md) | Provenance completeness and claim-mapping tests | Planned | Future source-linked response |
| Session memory | Must | Memory/graph; [graph design](graph-design.md), [testing strategy](testing-strategy.md) | Multi-turn, ownership, bounded-context tests | Planned | Future session replay |
| Knowledge search tool | Must | Tools/retrieval; [graph design](graph-design.md), [retrieval design](retrieval-design.md) | Authorization/schema/result contract tests | Planned | Future safe tool event |
| MCP tool | Must | `enterprise_ai.mcp_tools`; [MCP design](mcp-enterprise-tools-design.md) | Real protocol contract, allowlist, RBAC, timeout, cancellation, security, graph, event, and tracing tests | Implemented | Three local read-only fictional enterprise tools |
| Python analysis tool | Must | Restricted runtime; [architecture](architecture.md), [testing strategy](testing-strategy.md) | Role, resource, network/secret, escape tests | Planned | Future isolated job evidence |
| LangSmith traces | Must | Observability; [tracing design](langsmith-tracing-design.md), [testing strategy](testing-strategy.md) | Offline hierarchy, correlation, isolation, sanitization tests, and real remote smoke traces | Complete | Real external export, hierarchy, finalization, privacy, and denied-outcome metadata verified |
| Prompt-injection protection | Must | Security/graph; [graph design](graph-design.md), [testing strategy](testing-strategy.md) | Direct/indirect adversarial evaluation | Planned | Future blocked-input case |
| Input validation | Must | FastAPI/graph; [API contracts](api-contracts.md), [graph design](graph-design.md) | Boundary/size/schema fuzz and contract tests | Planned | Future safe 400/422 response |
| Retrieved-content validation | Must | Retrieval/security; [retrieval design](retrieval-design.md) | Malicious-document and policy-invariance tests | Planned | Future quarantine event |
| Tool authorization | Must | Backend policy; [graph design](graph-design.md), [ADR 0005](adr/0005-rbac-enforcement-boundary.md) | Exact tool-to-permission and role-denial matrix | Implemented | Typed policy decisions only; no tool executes |
| Hallucinated-citation protection | Must | Evidence/response; [retrieval design](retrieval-design.md), [graph design](graph-design.md) | Unknown/unused/unsupported citation tests | Planned | Future rejected citation |
| Brand-safety validation | Must | Response guardrail; [graph design](graph-design.md) | Versioned policy corpus and repair/refusal tests | Planned | Future guarded output |
| Viewer role | Must | Backend RBAC; [ADR 0005](adr/0005-rbac-enforcement-boundary.md) | Exact permission, tool, and access-level tests | Implemented | Viewer policy/denial tests; downstream features planned |
| Analyst role | Must | Backend RBAC; [ADR 0005](adr/0005-rbac-enforcement-boundary.md) | Exact permission, tool, and access-level tests | Implemented | Analyst policy tests; tools are not executed |
| Administrator role | Must | Backend RBAC; [ADR 0005](adr/0005-rbac-enforcement-boundary.md) | Complete defined permission/tool matrix and unknown-tool denial | Implemented | Administrator policy tests; admin business actions absent |
| Token-bucket rate limiting | Must | API/rate-limit; [architecture](architecture.md), [ADR 0007](adr/0007-token-bucket-rate-limiting.md) | Configuration, deterministic refill, concurrency, isolation, proxy, cleanup, failure and 429 tests | Implemented | Login and `/auth/me` policy tests; distributed Redis remains planned |
| Representative sample corpus | Must | `data/sample_documents`; [sample-data design](sample-data-design.md) | Generator check, independent validator, manifest/distribution/relationship tests | Implemented | 51 fictional documents and reproducible manifest |
| Recursive-research evaluation dataset | Must | `data/evaluation`; [sample-data design](sample-data-design.md) | Question count, route/type coverage and reference-integrity tests | Implemented | 12 evidence-expectation questions; no model answers |

## Recursive-research feature traceability

| Assignment requirement | Implementation | Tests/evidence | Status | Limitation |
| --- | --- | --- | --- | --- |
| LangGraph multi-agent orchestration | `enterprise_ai.graph`, `enterprise_ai.research.service`, compiled `Send` worker graph | compiled-round and final-determinism tests | Complete for offline PoC | No durable distributed workers |
| Supervisor/retrieval/research/response | Graph routing/nodes, research service/worker, grounded response service | graph, research, final evaluation tests | Complete for current scope | Deterministic classifiers/providers |
| Recursive research/RLM | Fake structured planner, child proposals, bounded later rounds | depth, child, plan-repair tests | Complete for bounded PoC | Not unrestricted recursion |
| Async retrieval/tools | Async offline adapter, worker and typed tool boundaries | concurrency, timeout, cancellation tests | Complete for offline path | No transport or remote tool delivery |
| Python analysis | Restricted typed analysis service and provenance | analysis budget/guardrail/evaluation tests | Complete for supported operations | Fixed operation taxonomy |
| Hybrid retrieval | Existing dense/sparse path; offline evaluation selects sparse adapter | sparse validation/evaluation and research benchmark | Partial | Final benchmark is BM25-only; no Pinecone network call |
| Attribution/citations | Authorized evidence ledger, grounding map, validator, bounded repair/fallback | citation tests and 12-question final evaluation | Complete for deterministic structural contract | Not general semantic entailment |
| Session memory | Bounded final turn and verified evidence references | memory and event-state tests | Complete for process-local PoC | No durable/distributed memory |
| RBAC | Central permissions/access-level enforcement at route, retrieval, aggregation and citations | role/mutation/authorization tests | Complete for current roles | No external identity provider integration |
| Graceful failure | Planner/worker/total deadlines, cancellation, budgets and deterministic fallback | timeout, cancellation, exhaustion and failure-event tests | Complete for offline PoC | Provider/service retry policy remains bounded |
| Agent activity | `GraphRuntime.astream()` validated public events | compiled stream, serialization and state-bound tests | Partial | Post-fan-in worker order; FastAPI/SSE/UI pending |
| LangSmith tracing | Application-owned safe spans with optional LangSmith export | Unit, integration, and real remote smoke tests | Complete | Successful and authorization-denied traces remotely verified |
| MCP tool | Official-SDK server/client, typed service models, deterministic graph node | Unit and graph integration suites | Complete for local read-only PoC | No remote transport or OAuth |
| Streamlit UI | Not in this commit | None | Pending | Mandatory later assignment work |
| Security test fixtures | Must | `data/security_fixtures`; [security design](security-design.md) | Isolation, separate manifest and exclusion tests | Implemented | 9 safe malicious-test-only fixtures |
| LLM failure handling | Must | Graph/services; [error handling](error-handling-design.md) | Unavailable/timeout/retry/fallback fault tests | Planned | Future partial/failure event |
| Vector-database failure handling | Must | Retrieval; [error handling](error-handling-design.md) | Transient/permanent retry and cancellation tests | Implemented | Offline fake-provider failures; endpoint fallback remains planned |
| MCP failure handling | Must | MCP/tools; [error handling](error-handling-design.md) | Unavailable, malformed protocol, timeout, and isolation tests | Implemented | Safe failure; no automatic retry |
| Tool timeout handling | Must | Tools/graph; [error handling](error-handling-design.md) | Cancellation, timeout, and isolation tests | Implemented for MCP/Python | Broader provider policies remain planned |
| Invalid-request handling | Must | API; [API contracts](api-contracts.md), [error handling](error-handling-design.md) | Error-envelope/schema/idempotency tests | Planned | Future structured error |
| Human-in-the-loop bonus | Bonus | Graph/UI; [graph design](graph-design.md), [roadmap](implementation-roadmap.md) | Pause/resume/deny/expiry tests | Planned | Future approval checkpoint |
| Reranking bonus | Bonus | Retrieval; [retrieval design](retrieval-design.md) | Blind comparative quality/latency evaluation | Planned | Future metrics comparison |
| Long-term memory bonus | Bonus | Memory; [roadmap](implementation-roadmap.md) | Consent, isolation, deletion, persistence tests | Planned | Future optional scenario |
| Feedback-loop bonus | Bonus | API/UI/evaluation; [API contracts](api-contracts.md), [roadmap](implementation-roadmap.md) | Ownership, persistence, privacy, evaluation-use tests | Planned | Future feedback record/report |
| Docker Compose bonus | Bonus | Deployment; [architecture](architecture.md), [roadmap](implementation-roadmap.md) | Clean-environment startup, isolation, E2E test | Planned | Future reproducible stack startup |
