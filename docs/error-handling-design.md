# Proposed Error-handling Design

Status: **Core paths implemented.** Retrieval, graph, research, analysis, generation, citation repair/fallback, memory, and trace export have bounded typed failure behavior. Hybrid can return an explicit safe partial result for one ordinary branch failure; authorization and integrity failures do not widen retrieval.

The chat API maps validation, authentication, quota, session ownership, timeout, dependency, and
unexpected failures to safe request-ID-bearing JSON errors before SSE begins. After headers are
sent, it emits at most one sanitized `stream.error` and never both error and completion. SDK
messages, exception types, stack traces, queries, evidence, credentials, and internal paths remain
private. See [FastAPI chat and SSE design](fastapi-chat-sse-design.md).

The Streamlit boundary maps pre-stream HTTP statuses to bounded user messages, honors a validated
numeric `Retry-After`, clears authentication on 401, and never automatically replays a chat turn.
Incremental parser, correlation, ordering, missing-terminal, interruption, and invalid-final-output
failures retain the submitted user message and safe activity but do not create an assistant answer.
Both the HTTP client and response are context-managed in success and failure paths. See
[the frontend design](streamlit-chat-ui-design.md).

Memory ownership and integrity errors fail closed. Disabled memory is stateless; non-security load
failures continue with a warning, and post-response update failures report that memory was not
saved without exposing stored content.
Restricted-analysis authorization, validation, dataset-integrity, limit, timeout, and calculation
failures are sanitized and never fall back to broader data or arbitrary execution.
Provider failures use bounded retry classes. Invalid citations receive one bounded same-context
repair and then a safe deterministic fallback; permanent authorization/attribution failures do not retry.
The response service also applies a hard per-call timeout and validates the provider result against
the typed generation schema. Unavailable, timed-out, malformed, or failed repair calls use an
authorized evidence-only fallback when configured; otherwise the graph emits one sanitized failed
terminal result and does not record the failed turn as completed memory.

## Taxonomy and default policy

| Category | Retry | Max retries / backoff | Fallback | Terminal outcome and public strategy |
|---|---|---|---|---|
| Validation | No | 0 | Correct request | `failed`; specific safe field guidance (`400/422`). |
| Authentication | No | 0 | Re-authenticate | `denied`; generic `401`, log no credential. |
| Authorization | No | 0 | None | `denied`; generic `403/404`, security audit. |
| Rate limit | Client retries after refill | 0 server retries | Retry after server value | `denied`; implemented `429` with bounded `Retry-After`. |
| Dependency failure | If transient/idempotent | 2, exponential 250 ms/1 s plus jitter | Cached/alternate path if authorized | `partial_success` or `failed`; name capability, not internals. |
| Timeout | Sometimes | At most 1 within deadline | Partial evidence/result | `partial_success` or `failed`; concise timeout message. |
| Transient | Yes | 2, exponential with jitter | Operation-specific | Continue, partial, or failed; trace every attempt. |
| Permanent | No | 0 | Operation-specific | `failed`; stable safe message. |
| Security-policy violation | No | 0 | Safe refusal | `denied`; audit policy rule ID internally only. |
| Partial-result condition | No broad retry | Failed subtask policy | Use validated successes | `partial_success`; disclose limitations. |
| Internal | No automatic whole-graph replay | 0 | Safe generic response | `failed`; generic message and correlated exception log. |

Logs contain request/trace IDs, typed code, operation, attempt, duration, and sanitized dependency metadata. Traces mark retries and fallbacks. Raw prompts, evidence text, secrets, credentials, stack traces in UI, and private reasoning are prohibited.

HTTP, stream, and graph outcome logs use an allowlist of correlation, route, status, dependency,
duration, role, cancellation, and disconnect fields. The JSON formatter ignores exception payloads
and unapproved `extra` fields and redacts credential patterns and internal paths in the fixed event
name.

## Failure matrix

| Condition | Handling | Result |
|---|---|---|
| LLM unavailable | Retry idempotent provider call up to 2 times; if a deterministic evidence-only response is explicitly supported, use it; otherwise stop. | Partial only when useful validated content exists; else failed. |
| LLM timeout | Cancel call, one retry with remaining deadline and reduced budget; never duplicate streamed text without sequence reset policy. | Partial or failed. |
| Pinecone unavailable | Retry twice; no unauthorized alternate corpus; tools may continue only if independent and useful. | Partial with “knowledge search unavailable,” or failed. |
| Pinecone timeout | Cancel, one retry with smaller candidate count if within policy/deadline. | Partial or failed. |
| MCP unavailable | Translate local protocol/transport failure without unrestricted fallback or raw SDK details. | Failed when MCP was the selected essential route. |
| MCP timeout | Cancel the bounded read-only operation; do not retry automatically. | Failed safely; caller cancellation remains distinct and propagates. |
| Python-analysis failure | Terminate isolated job, record sanitized stderr category only; do not run on host as fallback. | Partial or failed. |
| Invalid tool parameters | Reject before execution; allow one structured correction only if policy permits. | Denied for policy breach, otherwise failed subtask. |
| Citation-validation failure | One draft repair using the same evidence; never invent or retrieve merely to validate after streaming final text. | Success after repair or failed/partial without unsupported claims. |
| Memory-store failure | Continue statelessly when the current request has sufficient input; do not claim persistence. | Partial success with warning, or failed for session creation/read. |
| Streaming-client disconnect | Stop projection, release stream resources; continue/persist or cancel graph according to explicit request policy. | `cancelled` presentation or graph continues; internal trace records disconnect. |
| Recursive-research budget exhaustion | Stop new workers, aggregate completed validated results, mark gaps and limitations. | Partial success if sufficient; otherwise failed. |

### Submission failure evidence matrix

| Condition | Internal handling | Public response | Completion | Route | Retryability | Fallback | Expected Agent Activity |
|---|---|---|---|---|---|---|---|
| Invalid request | Strict schema/graph validation before capability execution | Safe request error | failed | none/failure | No | Correct request | validation failed; no tool |
| Unauthenticated or expired token | Bearer/JWT checks reject before graph use | Generic `401` | denied | none | Re-authenticate | None | No graph/tool activity |
| Rate limit | Atomic per-user bucket returns bounded `Retry-After` | Generic `429` | denied | none | Client after delay | Wait | No graph/tool activity |
| Session ownership conflict | Runtime and memory ownership fail closed | Safe conflict/denial | denied | failure | No | New conversation | No cross-user content |
| LLM unavailable with fallback | Typed provider error; authorized evidence-only fallback | Useful grounded fallback | completed | original route | Provider retry only | Deterministic extractive | fallback, citations, response completed |
| LLM unavailable without fallback | Typed error enters guarded failure handler | `The request failed safely.` | failed | failure | Provider-class dependent | None | generation failed, safe handler, response failed |
| Malformed structured output | Typed validation, one same-context repair, then fallback/failure | Repaired/fallback answer or safe failure | completed/failed | original/failure | One repair | Deterministic extractive | repair/fallback or safe handler |
| Retrieval unavailable | Typed retrieval failure; no unrelated substitution | Safe failed response | failed | failure | Dependency-specific | None when essential | retrieval failed, safe handler, response failed |
| Corrupt sparse artifacts | Schema/hash/fingerprint/count check fails before use | Safe failed response | failed | failure | No | Rebuild artifacts | retrieval failed, safe handler, response failed |
| Pinecone unavailable | Bounded dense timeout/retry; hybrid partial only when policy permits | Safe partial warning or failure | partial_success/failed | original/failure | Transient classes only | Authorized sparse branch | retrieval warning/completed or response failed |
| MCP unavailable | Typed protocol failure; no unrestricted tool fallback | Safe failed response | failed | failure | No automatic replay | None | MCP started/selected/failed, safe handler, response failed |
| Python-analysis failure | Typed aggregate boundary fails; no arbitrary execution | Safe failed response | failed | failure | No automatic replay | None | authorization, tool started/failed, safe handler, response failed |
| Citation validation failure | One same-evidence repair; unsupported claims cannot complete | Repaired/fallback answer or failure | completed/failed | original/failure | One repair | Authorized-evidence fallback | validation/repair/fallback or response failed |
| Tracing unavailable | Recorder errors isolated; bounded flush | Normal application response | unchanged | unchanged | Operational only | No-op recorder | Normal activity; no trace-error event |
| SSE disconnect | Iterator closes and cancellation/disconnect is logged; no false terminal | Interrupted client turn | cancelled presentation | unchanged internally | New explicit request | None | Only events received before disconnect |

Circuit breakers may be introduced after measurement; they must be per dependency and observable. Retries consume the original time/token/tool budget and use idempotency identifiers. One failed worker cannot mutate siblings or parent state; the reducer merges typed successful envelopes only.

Research workers convert timeouts and dependency failures into typed safe results. With partial results enabled, authorized sibling evidence survives and coverage records missing dimensions. Authorization failures are never widened or retried without filters. Exhaustion prevents new dispatch and final synthesis reports partial or exhausted status.

Once an application-level LLM call starts, its research budget unit is not refunded on timeout or cancellation. If no unit remains for synthesis or citation repair, no provider call starts and invalid drafts are replaced by deterministic evidence fallback or safe failure.

Repairable research-plan validation failures may consume one additional LLM unit and are recompiled once. Non-repairable security violations fail immediately. A still-invalid repaired plan fails safely without a third call or worker dispatch.

No evidence bypasses grounded generation: the deterministic fallback states that sufficient authorized evidence was unavailable and emits no citations. Partial and authorization-blocked coverage preserve only safe dimension names, never inaccessible source metadata.

Research exceptions are converted inside the research graph node into a sanitized `research.failed` event and typed graph failure while external cancellation continues to propagate. Failed research never emits the partial or successful research terminal event.

Planner component timeout and total research deadline are exercised separately. Both clean up blocked work, while cancellation of the public stream remains `CancelledError` and creates no false success/failure terminal or memory completion.

Rate-limit store failures, invalid policies, corrupted state, lock-path failures, malformed trusted-proxy input, and non-finite clock/input values fail closed with a sanitized retryable `503`; enforcement is never silently bypassed. Cancellation propagates. Negative clock elapsed time is clamped to zero. Bounded cleanup failure is safely logged and does not fail a request whose atomic enforcement already succeeded.
## Trace export failures

Trace start, finish, and flush failures are logged as generic operational warnings and never replace graph output or public events. Application exceptions retain safe typed categories in traces without exception messages or stack traces. `CancelledError` is re-raised after marking the in-memory span cancelled.
