# Streamlit Chat UI and Agent Activity Panel

Status: **Implemented.**

## Architecture

`frontend/streamlit_app.py` is the stable Streamlit entry point. It delegates to the
`frontend.enterprise_ai_frontend` package:

- `app.py` coordinates page reruns and widgets.
- `auth.py` renders login and performs the authentication transition.
- `api_client.py` owns synchronous HTTP and POST-SSE lifecycles.
- `sse.py` incrementally parses and validates the public stream contract.
- `state.py` centralizes all Streamlit session-state keys and transitions.
- `activity.py` projects public events into bounded, human-readable activity.
- `rendering.py` renders messages, citations, and safe provenance.
- `config.py`, `models.py`, and `errors.py` provide typed boundaries.

The frontend is presentation-only. FastAPI remains authoritative for identity, authorization,
routing, tools, graph execution, memory, rate limits, and event projection.

## Authentication and session state

The login form sends username and password directly to `POST /api/v1/auth/login`. Passwords are
masked and are never logged, cached, or stored. A validated access token is retained only in the
current browser session's `st.session_state`; it is sent only in the Authorization header. Safe
display name and role fields are retained separately.

Logout clears the token, user, backend session ID, displayed messages, activity, last output,
pending state, safe error, and request metadata. An HTTP 401 during chat performs the same cleanup
and returns to login without retrying the rejected token.

Frontend message history is presentational. Conversation continuation is controlled by the
backend-issued session UUID saved from a validated `GraphOutput`. New conversation clears that UUID
and presentation history while preserving authentication; no undocumented reset API is called.

## POST SSE client

The client POSTs only `message` and, for a continuation, `session_id` to
`/api/v1/chat/stream`. It requests `text/event-stream`, applies bounded connect/write/pool and
long-read timeouts, incrementally consumes bytes, and closes both response and client in all exit
paths. Browser `EventSource` is not used because it cannot issue the required authenticated JSON
POST.

The local parser supports `event`, `id`, multi-line `data`, blank-line termination, comments,
incremental UTF-8 decoding, CRLF/LF framing, incomplete-frame rejection, and a 256 KiB event bound.
Each decoded event must validate as `ChatStreamEnvelope`. A per-turn validator enforces:

- sequence numbers start at zero and increase by one;
- event IDs are unique;
- request, trace, and effective session IDs do not change;
- exactly one terminal event is received;
- no event follows a terminal event; and
- `response.completed` contains a correlated, valid `GraphOutput`.

Unknown future event names remain visible as generic activity but cannot bypass these invariants.
Partial activity is retained after interruption, but no assistant message is created without a
valid completed response.

## Agent Activity Panel

The sidebar timeline updates as each envelope arrives. It uses only public event fields: friendly
label, public status, sequence, timestamp, and allowlisted route, tool, result/evidence count, or
research-round detail. It never displays prompts, reasoning, graph state, evidence text, policies,
filters, JWT data, raw tool payloads, exceptions, or traces. Records are de-duplicated by event ID
and bounded by `FRONTEND_MAXIMUM_ACTIVITY_ITEMS` (default 100). Completed timelines remain available
in a collapsed expander.

Known mappings cover request/graph lifecycle, routing, retrieval, recursive research, MCP,
restricted analysis, generation, citation validation, memory, completion, denial, fallback, and
failure events. Unknown safe events use the neutral label `Agent activity`; the UI never invents an
event.

## Response, citation, and provenance rendering

A validated `response.completed` adds one assistant message keyed by request ID, saves the effective
session ID, and clears the pending flag. Reruns cannot duplicate that completion. The answer shows
completion status when meaningful, insufficient-evidence and deterministic-fallback warnings, and
only non-empty supporting sections.

Citations preserve the backend marker and display title, section, version, and update date. The UI
intentionally omits filesystem paths, source-line coordinates, internal evidence/chunk/document
UUIDs, access filters, and fake links. MCP provenance shows only the public tool and record
identifier. Restricted analysis shows only its public operation name, never rows or raw parameters.

## Failure handling and security

Pre-stream HTTP failures are mapped to bounded public messages for 400, 401, 409, 422, 429, 500,
503, and 504. A valid safe backend error may supply its public code/message/retryability, and a
bounded numeric `Retry-After` is shown. Raw or oversized bodies are ignored. Connection, timeout,
malformed-stream, missing-terminal, invalid-final-response, and in-stream errors never create a
false assistant answer or trigger an automatic chat retry.

User and backend text is rendered through ordinary Streamlit Markdown with
`unsafe_allow_html=False`. The frontend sends no role, permission, route, tool, namespace, trace,
or user identifier. Configuration accepts one environment-provided HTTP(S) origin and rejects
credentials, paths, query strings, fragments, and non-HTTP schemes. No user-specific value is
cached.

## Configuration and operation

Safe defaults:

```text
FRONTEND_API_BASE_URL=http://127.0.0.1:8000
FRONTEND_REQUEST_TIMEOUT_SECONDS=10
FRONTEND_STREAM_TIMEOUT_SECONDS=90
FRONTEND_APPLICATION_TITLE=Enterprise AI Knowledge Assistant
FRONTEND_MAXIMUM_ACTIVITY_ITEMS=100
```

Run from the repository root after configuring the backend's proof-of-concept identities:

```powershell
uvicorn enterprise_ai.main:app --factory --host 127.0.0.1 --port 8000
streamlit run frontend/streamlit_app.py
```

## Verification and limitations

Offline tests cover configuration, authentication responses, request minimization, SSE fragmentation
and invariants, response cleanup, state transitions, bounded activity, safe event projection, and
Streamlit rendering. Backend API tests remain the provider-side contract authority.

The frontend does not provide durable SSE replay, automatic non-idempotent retry, cross-device
history, token refresh, distributed session state, or an enterprise IdP. A browser refresh preserves
only Streamlit's current session lifetime. Production deployment still requires TLS, proxy buffering
and timeout validation, external identity, distributed backend memory/rate limits, and a secrets
manager.
