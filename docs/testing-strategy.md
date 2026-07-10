# Proposed Testing Strategy

Status: **Partially implemented.** Health, shared-contract, Argon2 password, strict JWT, login/current-user API, exact RBAC, tool mapping, retrieval authorization, safe error, and fail-fast configuration tests run now. Graph, retrieval execution, tool execution, streaming, and end-to-end assistant tests remain planned. Tests use generated documents and synthetic identities; no production data or credentials.

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

Required local gates remain `ruff format --check .`, `ruff check .`, `mypy backend/src frontend`, and `pytest`. Future CI adds coverage thresholds only where meaningful, OpenAPI/event snapshots with intentional review, dependency/security scanning, and Mermaid rendering. Demo evidence references test names, sanitized event captures, trace IDs, and evaluation reports—never claims a designed feature is operational before its tests pass.
