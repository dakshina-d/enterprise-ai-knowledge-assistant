# Event-stream Baseline and Target Design

The baseline graph now creates versioned, allowlisted `AgentEvent` models with correlated request,
trace, and session IDs, monotonic per-invocation sequence numbers, and exactly one terminal event.
`enterprise_ai.graph.cli stream` exposes the safe typed async stream for offline inspection.
FastAPI SSE transport and Streamlit UI rendering are implemented. Durable reconnect/replay remains
proposed below.
Memory load, context-resolution, update, eviction, and failure events share this sequence and expose
only safe counts/status—not prior messages, ownership records, or evidence bodies.
Python-analysis events expose authorization outcome, tool lifecycle, and bounded result counts;
they never expose dataset rows, root-cause text, parameters, or policy internals.
Generation, citation-validation, repair, and fallback activity is emitted before one terminal event;
unvalidated provider tokens and drafts are never streamed.

Status: **The versioned public event envelope, allowlisted payload model, native FastAPI POST SSE
transport, and validated Streamlit consumption are implemented; durable replay remains planned.**
The UI incrementally validates sequence, correlation, unique IDs, and exactly one terminal event
before accepting a final response.

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

The event projector uses an allowlist schema per event type; it does not serialize graph state.
Workflow and Agent Activity events stream in real time through SSE. Local Ollama uses a
non-streaming schema-constrained generation call, so validated model output is attached only to the
terminal response envelope; token-by-token model streaming is not claimed. Disconnect closes the
presentation iterator while graph cancellation/persistence follows explicit policy; no endless
retry loop is created.

Research progress contains allowlisted plan/task identifiers, depth/round, counts, status, budget usage, and duration only. Evidence bodies, prompts, raw provider output, restricted titles, and hidden reasoning are excluded. Worker lifecycle events are currently synthesized from the deterministic post-fan-in result order; they do not claim to expose real-time parallel completion order. Final worker and evidence collections are separately sorted for deterministic output. Truthful live completion ordering is deferred until an application-owned event callback or transport boundary exists.

Worker payloads include task ID, parent task ID where applicable, depth, and round. Sufficient research emits `research.completed`; partial or insufficient research emits `research.partial` instead, and failed research emits `research.failed`. Analysis and child-task events occur only when those operations occurred.

The public runtime consumes LangGraph v2 custom/value streams. Custom events are validated as `AgentEvent`; a final value is projected exactly once, only after one terminal response event. Sequence allocation starts at zero per invocation, remains monotonic through research fan-out, and concurrent invocations use independent counters and event IDs. Graph update history is not separately projected as public events, preventing duplication.

Research start and planning-start events are emitted before the awaited research operation, so timeout/failure streams remain truthful. Outcome events are mutually exclusive: sufficient emits `research.completed`, partial/insufficient emits `research.partial`, and failed emits `research.failed`. `POST /api/v1/chat/stream` now projects `GraphRuntime.astream()` through native SSE, folds the terminal graph event with the one final output, and closes the iterator on disconnect. Durable replay remains deferred.

Planner timeout and total-deadline streams retain pre-failure lifecycle events, emit one sanitized research failure, and end with one failed response/output. External consumer cancellation propagates without inventing a terminal event. Budget exhaustion emits one bounded budget event; if no usable evidence survives, later evidence validation may select the failed response terminal.

`GraphRuntime.astream()` rejects schema-invalid, correlation-mismatched, or out-of-sequence custom events before public projection. Invalid operational events are dropped; the valid invocation stream continues to one safe terminal/output. Retained `activity_events` are capped at 200 with deterministic oldest-first eviction, while sequence allocation advances from the last retained sequence so live numbering never repeats after eviction.
