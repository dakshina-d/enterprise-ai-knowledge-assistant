# FastAPI Chat and SSE Design

Status: **Implemented.** The Streamlit client and Activity Panel remain planned.

## Endpoints and contracts

`POST /api/v1/chat` authenticates and rate-limits one request, constructs a server-owned
`GraphInput`, calls the shared runtime's `ainvoke()` once, and returns the validated
`GraphOutput`. `POST /api/v1/chat/stream` performs the same boundary checks and consumes
`GraphRuntime.astream()` once through FastAPI's native `EventSourceResponse` and
`ServerSentEvent` support.

The strict request body accepts only `message`, optional `session_id`, and optional `top_k`.
Messages are nonblank and limited to 4,000 characters; `top_k` is 1–100. Identity, role,
permissions, trace identifiers, routes, tools, namespaces, filters, and build fingerprints
cannot be supplied in the body. The server creates request and trace UUIDs and creates a session
UUID when omitted.

## Authentication, quotas, and sessions

Both endpoints require a validated Bearer access token. Viewer, Analyst, and Administrator roles
may submit chat turns; graph and service boundaries retain tool-specific authorization. The
existing atomic per-user standard token bucket is shared by JSON and streaming calls, and a 429
response occurs before graph execution. Runtime and memory ownership bind a session to user, role,
and permission policy; a mismatched reuse returns a nondisclosing 409 response.

## Streaming

Each named SSE message contains an application-owned JSON envelope with a unique event ID,
strictly increasing sequence, request/trace/session IDs, timestamp, stable event type, and one
allowlisted graph event, final response, or safe error. `stream.started` is first. The graph's
terminal event is held until its validated final output arrives, producing exactly one terminal
event and exactly one final response. An exception after streaming begins produces at most one
`stream.error`, never a completion event.

FastAPI performs SSE framing and periodic keepalive comments; application code never concatenates
frames. Responses use `text/event-stream`, `Cache-Control: no-cache, no-transform`, and
`X-Accel-Buffering: no`, with no response compression. Streamlit must consume this POST endpoint
with an HTTP streaming client because the browser `EventSource` constructor supports GET only.

On disconnect or caller cancellation, the pending graph iteration is cancelled and the async
iterator is closed. Cancellation is re-raised, is not logged as an application failure, and no
false completion event is emitted. The graph's existing cancellation semantics prevent a
completed memory turn from being written.

## Lifecycle, privacy, and errors

FastAPI lifespan creates one process-owned graph runtime and calls `GraphRuntime.aclose()` exactly
once at shutdown. That existing shutdown closes response-provider resources and flushes the safe
LangSmith tracer. Tests inject a bounded fake runtime; the default runtime remains offline-safe
unless optional providers are explicitly enabled.

Request logs contain generated identifiers, endpoint, method, status, role/outcome summaries, and
duration category. They exclude messages, responses, evidence, tokens, cookies, credentials,
prompts, tool results, and exception text. The HTTP layer does not add a second assistant root
trace or trace bodies.

Before streaming, authentication, validation, quota, ownership, timeout, and internal failures use
sanitized JSON errors with a request ID. After headers start, only `stream.error` is available.
General responses add `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a
server-owned `X-Request-ID`.

CORS accepts only configured exact origins, explicit GET/POST/OPTIONS methods, and Authorization
and Content-Type headers. Wildcard credentialed origins are rejected by configuration.

## Running and manual checks

Start the actual factory:

```bash
uvicorn enterprise_ai.main:app --factory --host 127.0.0.1 --port 8000
```

After obtaining a temporary token from the existing login endpoint:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message":"Who owns the payment-gateway service?"}'

curl -N -X POST http://127.0.0.1:8000/api/v1/chat/stream \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message":"Identify recurring payment incident causes."}'
```

Known limitations are process-local quotas, checkpoints, session ownership, and memory; there is
no durable SSE replay or transport idempotency key. Multi-worker deployment requires shared atomic
quota/session/checkpoint infrastructure. Streamlit integration is intentionally not part of this
phase.
