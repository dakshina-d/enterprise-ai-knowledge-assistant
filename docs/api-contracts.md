# Proposed API Contracts

Status: **Designed, not implemented**, except the two health endpoints. JSON APIs use `/api/v1`, UTC timestamps, opaque identifiers, and a consistent error body. Authentication is a secure HTTP-only session cookie for the PoC (bearer tokens are a production alternative). Role values are `viewer`, `analyst`, and `administrator`.

## Common contracts

```json
{
  "error": {
    "code": "validation.invalid_request",
    "message": "The request could not be accepted.",
    "request_id": "req_01...",
    "retryable": false,
    "details": []
  }
}
```

Never include stack traces, secrets, raw prompts, authorization-policy internals, or provider responses. Mutating POSTs accept an `Idempotency-Key`; keys are scoped to user, route, and canonical request hash with a bounded retention period. Reuse with different content returns `409`.

## Endpoint summary

| Endpoint | Purpose | Authentication | Roles | Idempotency / streaming |
|---|---|---|---|---|
| `GET /health/live` | Process liveness. | None | Public | Safe GET; no streaming. Implemented. |
| `GET /health/ready` | Dependency readiness. | None | Public | Safe GET; currently placeholder readiness. |
| `POST /api/v1/auth/login` | Establish PoC demonstration identity/session. | None | Valid configured demo identity | Idempotency not required; rate-limited; no streaming. |
| `POST /api/v1/chat/sessions` | Create an owned conversation session. | Required | All roles | Idempotency key recommended; no streaming. |
| `POST /api/v1/chat/sessions/{session_id}/messages` | Validate and accept one user turn. | Required; session owner | All roles, with route/tool restrictions | Idempotency key required; returns acceptance, tokens stream separately. |
| `GET /api/v1/chat/sessions/{session_id}` | Read authorized session and completed turns. | Required; session owner/admin policy | All roles | Safe GET; no streaming. |
| `GET /api/v1/chat/sessions/{session_id}/events` | Stream safe events for an authorized request/session. | Required; session owner | All roles | SSE; supports `Last-Event-ID`. |
| `POST /api/v1/feedback` | Record feedback against an owned response. | Required | All roles | Idempotency key recommended; no streaming. |

Administrative ingestion endpoints are deferred. Offline CLI/job ingestion avoids exposing a high-risk upload/index mutation surface in the PoC. If remote administration becomes necessary, it requires a separate ADR, administrator-only policy, malware/file validation, audit trail, asynchronous jobs, and explicit idempotency.

## Endpoint details

### `GET /health/live`

- Request: no body.
- `200`: `{"status":"healthy"}`.
- Errors: `503` only if the process cannot serve; orchestration normally observes connection failure.
- Notes: no dependency calls and no sensitive build/config details.

### `GET /health/ready`

- Request: no body.
- `200`: `{"status":"healthy","checks":{}}` is the proposed future shape; current response is `{"status":"healthy"}`.
- Errors: `503` with safe failed-check names when required dependencies make the instance unable to accept work.
- Notes: checks are bounded/cached; readiness does not leak endpoints or credentials.

### `POST /api/v1/auth/login`

- Request: `{"username":"demo-viewer","password":"<secret>"}`. Demonstration-only credentials must come from configuration, not source code.
- `200`: `{"user":{"user_id":"usr_...","display_name":"Demo Viewer","role":"viewer"},"expires_at":"..."}` plus secure cookie.
- Errors: `400` malformed, `401` invalid credentials, `429` rate limited, `503` identity service unavailable.
- Security: generic authentication failure messages; rotate session on login; production uses an enterprise IdP/OIDC rather than this endpoint.

### `POST /api/v1/chat/sessions`

- Request: `{"title":"Optional title"}`; title is bounded and sanitized.
- `201`: `{"session_id":"ses_...","title":"...","created_at":"...","status":"active"}`.
- Errors: `400/422` validation, `401`, `403`, `409` idempotency conflict, `429`, `503` memory unavailable.
- Ownership: user ID is taken from identity, never request JSON.

### `POST /api/v1/chat/sessions/{session_id}/messages`

- Request: `{"content":"Question","client_message_id":"...","attachments":[]}`. PoC attachments default to unsupported; content and history have explicit size limits.
- `202`: `{"request_id":"req_...","message_id":"msg_...","status":"accepted","events_url":"/api/v1/chat/sessions/ses_.../events?request_id=req_..."}`.
- Errors: `400/422`, `401`, `403` wrong owner/role, `404` non-disclosing session miss, `409` duplicate conflict/session closed, `429`, `503` unable to accept.
- Behavior: acceptance is synchronous; graph work is asynchronous; safe activity and answer tokens arrive via SSE. A repeated idempotency key returns the original acceptance/result reference.

### `GET /api/v1/chat/sessions/{session_id}`

- Query: optional bounded `before` cursor and `limit`.
- `200`: session metadata and an ordered page of `{message_id, role, content, citations, created_at, status}`. Only authorized, final user-visible content is returned.
- Errors: `400`, `401`, `403/404` according to non-enumeration policy, `503` memory unavailable.
- Caching: private/no-store for the PoC; cursor is opaque.

### `GET /api/v1/chat/sessions/{session_id}/events`

- Query: required `request_id`; optional access token mechanism only if secure cookies cannot cover the stream. Never place long-lived bearer tokens in URLs.
- `200`: `text/event-stream` using the versioned envelope in [event-stream design](event-stream-design.md).
- Errors before headers: `400`, `401`, `403/404`, `409` request/session mismatch, `410` replay expired, `429`. After streaming starts, failures are typed `response.failed` events followed by close.
- Behavior: sends answer tokens, agent-state updates, tool/retrieval/validation events, and one completion/error event. Heartbeats keep intermediaries from closing idle connections. Reconnect uses `Last-Event-ID`; sequence numbers deduplicate events.

### `POST /api/v1/feedback`

- Request: `{"session_id":"ses_...","request_id":"req_...","rating":"up","reason_code":"helpful","comment":"Optional bounded text"}`.
- `201`: `{"feedback_id":"fb_...","status":"recorded"}`; identical idempotent replay returns the original record.
- Errors: `400/422`, `401`, `403` feedback on another user's response, `404`, `409`, `429`, `503` store unavailable.
- Privacy: comment is untrusted user input and excluded from ordinary logs/traces.

## SSE decision

SSE is chosen because the application needs one-way server-to-browser streaming while user actions remain ordinary authenticated POSTs. Named events naturally represent answer tokens, agent-state updates, tool calls, retrieval, validation, completion, and error events. Browser/proxy support, reconnection, and simple FastAPI response handling outweigh WebSocket bidirectionality for this PoC. Production must validate proxy buffering/timeouts and may add a durable event broker when multi-worker replay is required.
