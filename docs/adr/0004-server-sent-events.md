# ADR 0004: Server-Sent Events for UI Streaming

- Status: Accepted (design decision; implementation planned)
- Date: 2026-07-10

## Context

The UI needs one-way answer tokens and safe graph, retrieval, tool, validation, completion, and error updates. User commands can remain normal HTTP POST requests.

## Decision

Use authenticated SSE with a versioned JSON event envelope, monotonic per-request sequence numbers, event IDs, heartbeats, bounded replay, and exactly one terminal event.

## Alternatives considered

- WebSockets: bidirectional but unnecessary complexity for the PoC and harder conventional HTTP operations.
- Polling: simple but inefficient and poor for tokens/activity.
- NDJSON/chunked response: streamable but weaker named-event/reconnect conventions.

## Consequences

SSE works through common HTTP infrastructure and has straightforward browser semantics. It is one-way, connection-limited in some environments, and requires proxy buffering/timeout validation. Multi-worker durable replay may later need a broker.

## Security implications

Streams require session/request ownership checks. Per-event allowlist projection prevents graph-state leakage. Raw prompts, secrets, hidden reasoning, credentials, unauthorized evidence, and confidential metadata are never streamed.
