# Proposed Error-handling Design

Status: **Core paths implemented.** Retrieval, graph, research, analysis, generation, citation repair/fallback, memory, and trace export have bounded typed failure behavior. Hybrid can return an explicit safe partial result for one ordinary branch failure; authorization and integrity failures do not widen retrieval.

The chat API maps validation, authentication, quota, session ownership, timeout, dependency, and
unexpected failures to safe request-ID-bearing JSON errors before SSE begins. After headers are
sent, it emits at most one sanitized `stream.error` and never both error and completion. SDK
messages, exception types, stack traces, queries, evidence, credentials, and internal paths remain
private. See [FastAPI chat and SSE design](fastapi-chat-sse-design.md).

Memory ownership and integrity errors fail closed. Disabled memory is stateless; non-security load
failures continue with a warning, and post-response update failures report that memory was not
saved without exposing stored content.
Restricted-analysis authorization, validation, dataset-integrity, limit, timeout, and calculation
failures are sanitized and never fall back to broader data or arbitrary execution.
Provider failures use bounded retry classes. Invalid citations receive one bounded same-context
repair and then a safe deterministic fallback; permanent authorization/attribution failures do not retry.

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
