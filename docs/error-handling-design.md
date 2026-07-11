# Proposed Error-handling Design

Status: **Partially implemented.** Dense and sparse/hybrid retrieval have typed validation, timeout, dependency, authorization, stale-artifact, score, and attribution failures. Hybrid can return an explicit safe partial result for one ordinary branch failure; authorization and integrity failures do not widen retrieval. The broader graph/LLM fallback design remains planned.

Memory ownership and integrity errors fail closed. Disabled memory is stateless; non-security load
failures continue with a warning, and post-response update failures report that memory was not
saved without exposing stored content.
Restricted-analysis authorization, validation, dataset-integrity, limit, timeout, and calculation
failures are sanitized and never fall back to broader data or arbitrary execution.

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
| MCP unavailable | Retry discovery/call once if idempotent; continue with retrieval/other results. | Usually partial; failed if MCP was essential. |
| MCP timeout | Cancel remote call; no blind retry of non-idempotent tool; retain successful sibling results. | Partial or failed. |
| Python-analysis failure | Terminate isolated job, record sanitized stderr category only; do not run on host as fallback. | Partial or failed. |
| Invalid tool parameters | Reject before execution; allow one structured correction only if policy permits. | Denied for policy breach, otherwise failed subtask. |
| Citation-validation failure | One draft repair using the same evidence; never invent or retrieve merely to validate after streaming final text. | Success after repair or failed/partial without unsupported claims. |
| Memory-store failure | Continue statelessly when the current request has sufficient input; do not claim persistence. | Partial success with warning, or failed for session creation/read. |
| Streaming-client disconnect | Stop projection, release stream resources; continue/persist or cancel graph according to explicit request policy. | `cancelled` presentation or graph continues; internal trace records disconnect. |
| Recursive-research budget exhaustion | Stop new workers, aggregate completed validated results, mark gaps and limitations. | Partial success if sufficient; otherwise failed. |

Circuit breakers may be introduced after measurement; they must be per dependency and observable. Retries consume the original time/token/tool budget and use idempotency identifiers. One failed worker cannot mutate siblings or parent state; the reducer merges typed successful envelopes only.

Rate-limit store failures, invalid policies, corrupted state, lock-path failures, malformed trusted-proxy input, and non-finite clock/input values fail closed with a sanitized retryable `503`; enforcement is never silently bypassed. Cancellation propagates. Negative clock elapsed time is clamped to zero. Bounded cleanup failure is safely logged and does not fail a request whose atomic enforcement already succeeded.
