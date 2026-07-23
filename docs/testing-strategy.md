# Proposed Testing Strategy

Status: **Partially implemented.** Dense tests plus offline analyzer, BM25, sparse artifact/fingerprint, exact identifier, RBAC, normalization, fusion, attribution, deterministic ordering, and partial-result tests run now. Live Pinecone remains explicit and opt-in. Reranking, graph/tools, streaming, and end-to-end assistant tests remain planned.

Memory tests cover ownership, immutable snapshots, idempotency conflicts, sequences, TTL, eviction,
concurrency, sanitization, structured context, follow-up resolution, lifecycle ordering, and repeated
graph invocations within one runtime.
Restricted-analysis tests cover role scope, corpus hashes/paths, taxonomy rules, deterministic
aggregates and provenance, cancellation, graph routing, and static prohibited-primitive scanning.
Grounded-response tests use a deterministic fake for context bounds, citation mapping, invented-ID
repair/fallback, no-evidence abstention, prompt-injection isolation, and explicit provider closure.

## Repository CI

`.github/workflows/ci.yml` runs one authoritative Ubuntu validation job with Python 3.12 for pushes
to `main`, pull requests targeting `main`, and manual dispatch. The job installs `.[dev]`, runs
`pip check`, then executes corpus, ingestion, sparse-index/evaluation, Ruff, strict MyPy, and the
complete Pytest suite. It finishes with `git diff --exit-code` to detect mutations from read-only
checks and uploads `artifacts/pytest-results.xml` for seven days even after failure.

CI explicitly disables Pinecone live tests, selects the fake LLM provider, and requires no secrets.
OpenAI and Pinecone live coverage belongs in separately authorized future workflows. The workflow
uses the ordinary `pull_request` event rather than `pull_request_target`; untrusted contributor code
therefore does not execute with target-repository write permissions or secrets. Permissions are
limited to `contents: read`, checkout credentials are not persisted, and superseded branch/PR runs
are cancelled.

Run the same checks locally using the commands in the README quality, corpus, ingestion, and sparse
sections. Inspect the `pytest-results-<run-id>` artifact when a GitHub test failure needs JUnit
details. Branch protection should require `Repository CI / Quality and tests` after its first
successful run. CI validates but does not deploy, publish containers, call live providers, or prove
behavior on every operating system.

## Test layers

| Layer | Scope and examples | Gate |
|---|---|---|
| Unit | Models, validators, policy functions, token bucket, reducers, fusion, citation checks, event projection. | Every commit; deterministic and no network. |
| Integration | FastAPI with memory/rate-limit adapters, Pinecone test index, MCP test server, restricted-runtime adapter. | Feature branch/CI with isolated resources. |
| Contract | OpenAPI schemas, error envelope, SSE envelope/version compatibility, MCP/tool schemas, provider adapters. | Consumer/provider fixtures in CI. |
| Security | RBAC matrix, IDOR, injection corpus, filter enforcement, secret/log/event redaction, sandbox escape attempts. | Required before each trust boundary is demoed. |
| Retrieval quality | Golden queries, access labels, recall@k, nDCG/MRR, citation precision, duplicate rate, latency. | Versioned evaluation with regression thresholds. |
| Graph routing | State invariants, route table, retries, budgets, fan-out reducers, terminal states. | Property/table-driven tests in CI. |
| Failure injection | LLM/Pinecone/MCP/memory timeouts, malformed results, partial workers, disconnects. | Deterministic fake adapters plus selected integration faults. |
| Streaming | Ordering, monotonic sequence, reconnect/replay, heartbeat, one terminal event, redaction, slow/disconnected client. | SSE parser contract and API integration tests. |
| End-to-end | Login, session, multi-turn question, retrieval, authorized tool, streamed completion, feedback. | Clean PoC deployment with generated data. |
| LangSmith trace | Required span names, correlation IDs, route/tool/error attributes, no sensitive content. | Mock exporter in CI; selected real-project smoke test. |

MCP tests use the official SDK's connected in-memory client/server streams rather than direct tool
function calls. They cover discovery and result schemas, authorization-before-session creation,
malicious selectors, timeout, cancellation, concurrency, graph events/provenance, trace redaction,
and deterministic shutdown.

Observability tests inject the application recorder rather than mocking graph business logic. They verify disabled mode, allowlisted metadata, parent relationships, concurrent context isolation, cancellation propagation, transport failure isolation, and normalized graph-output equivalence. Network access and credentials are never required in CI.
| Manual demo | Positive role flows, denied actions, malicious document, partial dependency failure, bounded research. | Scripted checklist with saved non-sensitive evidence. |

Use fakes for LLM behavior rather than asserting exact generated prose. Freeze clocks/randomness for token-bucket/backoff tests. Integration resources use unique namespaces and cleanup. Evaluation thresholds and corpus versions are committed alongside results.

## Critical acceptance scenarios

| Scenario | Required assertion |
|---|---|
| Viewer cannot use analyst tools | Backend `authorize_tool` denies before execution; denial is safely streamed/audited. |
| Viewer cannot retrieve restricted documents | Mandatory filter excludes them and post-query recheck fails closed; zero restricted evidence reaches model fixture. |
| Analyst can use approved analysis tools | Allowlisted operation and scoped data execute in restricted adapter; result is sanitized. |
| Administrator can use all approved tools | Every approved tool passes policy; “administrator” still cannot invoke unknown tools. |
| LLM cannot bypass backend authorization | Malicious tool proposal and injected “admin” instruction are denied by deterministic policy. |
| Malicious document instructions are ignored | Content is marked untrusted, cannot change route/tool policy, and is quarantined or safely delimited. |
| Hallucinated citation is rejected | Unknown/unsupported evidence ID fails validation; never appears in final response. |
| Pinecone failure degrades gracefully | Bounded retry; useful independent result yields partial status, otherwise safe failure. |
| MCP timeout produces a partial result | Timed-out worker cannot erase successful evidence; response discloses limitation. |
| Recursion is bounded | Depth, worker count, tokens, calls, and deadline prevent another batch and terminate deterministically. |
| Failed research batch preserves successes | Worker-local failure envelope is excluded by reducer; successful siblings retain integrity. |
| Conversation context works across turns | Same owner receives bounded prior context; other sessions/users cannot access it. |
| Rate limiting is isolated per user | Exhausting one bucket does not change another; refill and concurrency are deterministic. |
| Sensitive data absent from logs/events | Canary secrets/raw prompts/confidential metadata never appear in captured logs, traces, or SSE. |

Additional negative tests cover invalid IDs, oversized input, replayed idempotency keys, session ownership, missing metadata, duplicate chunks, unsupported citations, tool argument fuzzing, Python resource limits, event replay expiration, and cancellation.

## Quality and evidence

Research verification covers plan compilation, executable `Send` fan-out, reducer safety, atomic budgets, recursive termination, restricted analysis by role, evidence deduplication, structural conflicts, deterministic coverage, grounded citations, partial failures, and the committed 12-question offline evaluation. Evaluation reports retrieval and orchestration metrics but does not equate recall with answer correctness.

Focused shared-budget tests cover exhaustion before synthesis, exhaustion before citation repair, invalid-citation suppression, concurrent atomic reservation, and per-request ledger isolation. Deterministic coverage is asserted to consume no LLM unit.

Structured-conflict tests cover UTC-equivalent timestamps, malformed/naive values, invalid ranges, policy dates, ownership, teams, departments, mappings, authority preference, deterministic IDs, and authorization suppression. Plan-repair tests cover success, no budget, malicious plans, and an invalid repair.

Analytical-output tests inject altered calculations, identifiers, scope, taxonomy, scripts, URLs, and policy-changing instructions and assert deterministic typed rendering. Insufficient-evidence tests cover bounded child depth, empty evidence, one-sided comparison, safe authorization blocking, and citation absence.

Research event tests consume the compiled graph's public custom/value stream and cover terminal/output cardinality, child worker lifecycles, payload safety, monotonic sequences, event-ID uniqueness, correlation consistency, and concurrent invocation isolation.

Compiled sufficient and failed streams additionally verify mutually exclusive research outcomes, one response terminal, one final output, valid citation-generation ordering, and no partial event on mandatory failure.

Failure-stream tests cover planner timeout, total deadline, explicit task-budget exhaustion, and external stream cancellation through the compiled public runtime. They assert cleanup, safe payloads, singular terminals/outputs, and absence of post-termination operations.

Event-state tests cover invalid schema projection, safe terminal continuation, retained-history eviction at 200 events, monotonic allocation after eviction, and absence of research event history/internal ledgers from conversation memory.

Final-pipeline evaluation tests execute all 12 questions twice through the compiled graph and compare aggregate/per-question output. Security integrity failures are fatal while honest non-sufficient outcomes are accepted. A gated three-worker compiled fixture proves byte-equivalent normalized final plans, task/ledger ordering, budgets, provenance, conflicts, coverage, citations, final response and memory-safe turn across three completion permutations. No test uses credentials, network calls, long sleeps, or generated repository output.

Required local gates remain `ruff format --check .`, `ruff check .`, `mypy backend/src frontend`, and `pytest`. Future CI adds coverage thresholds only where meaningful, OpenAPI/event snapshots with intentional review, dependency/security scanning, and Mermaid rendering. Demo evidence references test names, sanitized event captures, trace IDs, and evaluation reports—never claims a designed feature is operational before its tests pass.

The implemented chat delivery suite adds strict request-schema and injection tests,
authentication-before-execution and shared-quota checks, runtime lifespan verification, JSON
correlation/session checks, native SSE headers and parsing, monotonic unique envelopes, one final
terminal output, safe stream errors, and disconnect-driven iterator closure. The MyPy gate now
uses `mypy backend/src frontend ingestion/src scripts`.

The offline frontend suite adds configuration validation; login success, rejection, unavailability,
and malformed-response cases; request field/header checks; fragmented UTF-8 and multiline SSE;
keepalive, size, ordering, correlation, uniqueness, terminal, and cleanup invariants; idempotent
completion and bounded session state; safe activity projection; and Streamlit login/authenticated
layout, message, source, activity, error, and logout smoke checks. Mock transports and public typed
fixtures require no backend, browser, network, token, or credential.
