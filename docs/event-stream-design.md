# Event-stream Baseline and Target Design

The baseline graph now creates versioned, allowlisted `AgentEvent` models with correlated request,
trace, and session IDs, monotonic per-invocation sequence numbers, and exactly one terminal event.
`enterprise_ai.graph.cli stream` exposes the safe typed async stream for offline inspection.
FastAPI SSE transport, reconnect/replay semantics, and UI rendering remain proposed below.
Memory load, context-resolution, update, eviction, and failure events share this sequence and expose
only safe counts/status—not prior messages, ownership records, or evidence bodies.

Status: **The versioned public event envelope and allowlisted payload model are implemented; SSE transport remains planned.** The PoC will use authenticated Server-Sent Events (SSE) for one-way FastAPI-to-Streamlit delivery. SSE fits token and activity updates, supports event IDs and reconnection, works over ordinary HTTP, and is simpler than WebSockets when the client sends commands through normal POST requests.

## Versioned public envelope

```json
{
  "event_id": "evt_01...",
  "event_type": "node.completed",
  "event_version": "1.0",
  "sequence_number": 12,
  "request_id": "req_01...",
  "session_id": "ses_01...",
  "trace_id": "trc_01...",
  "timestamp": "2026-07-10T12:00:00Z",
  "node": "validate_evidence",
  "status": "completed",
  "public_message": "Evidence validated",
  "payload": {}
}
```

`event_id` is also sent as the SSE `id`; `event_type` is the SSE `event`; JSON is the `data`. Sequence numbers are monotonic per request. Unknown minor-version fields must be ignored; breaking envelope changes require a new major version. Heartbeat comments contain no data. Reconnect uses `Last-Event-ID`; the PoC may offer only an in-memory replay buffer and must document loss after restart.

The implemented contract uses `research.batch_completed` consistently (not `research.batch.completed`) and a typed `PublicAgentEventPayload` allowlist instead of an unrestricted mapping.

## Event catalogue

| Event type | Safe payload example |
|---|---|
| `request.accepted` | Request ID and queue/accepted status. |
| `graph.started` | Public workflow label. |
| `node.started`, `node.completed`, `node.failed` | Allowlisted node name, duration band, safe status. |
| `route.selected` | `simple_retrieval` or `recursive_research`, not hidden reasoning. |
| `retrieval.started`, `retrieval.completed` | Query count, authorized result count, duration; no raw query/chunks. |
| `tool.authorization_started` | Public tool category. |
| `tool.authorized`, `tool.denied` | Safe tool name and policy outcome; no confidential reason details. |
| `tool.started`, `tool.completed`, `tool.failed` | Tool category, safe summary, duration/status. |
| `research.batch_started`, `research.batch_completed` | Batch/depth and success/failure counts. |
| `validation.completed` | Validation type and pass/warn/fail. |
| `memory.updated` | Boolean/status only, never memory content. |
| `response.token` | Validated incremental text fragment and position. |
| `response.completed` | Final response metadata and citations or final response reference. |
| `response.failed` | Public error code, safe message, retry guidance. |

Retrieval, tool, validation, and agent-state events give the activity panel useful progress. `response.token` supports answer streaming. Completion/error events terminate a request stream exactly once.

## Information classification

- **User-visible:** public node labels, coarse route, safe progress messages, authorized citation metadata, token fragments, typed public errors.
- **Internal diagnostics:** stack traces, provider request IDs, retry counts, score details, latency, policy rule IDs, full tool outcomes; these belong in access-controlled logs/traces with redaction.
- **Never emitted:** raw prompts, system/developer instructions, private chain-of-thought or hidden reasoning, secrets, credentials/tokens, raw memory, unauthorized document text, confidential metadata, provider keys, connection strings, or unrestricted tool arguments/results.

The event projector uses an allowlist schema per event type; it does not serialize graph state. Tokens pass output policy before emission or use buffered sentence-level validation when token-by-token validation is unsafe. Disconnect cancels optional presentation streaming but graph cancellation/persistence follows explicit policy; no endless retry loop is created.
