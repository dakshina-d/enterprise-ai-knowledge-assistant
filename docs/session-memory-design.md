# Session Conversational Memory

Status: **implemented for one running process**. This feature retains a bounded set of safe,
user-visible turns and deterministic context. It is not long-term, semantic, durable, distributed,
or LLM-generated memory.

## Boundary and lifecycle

LangGraph's checkpointer records execution state and node continuity. `ConversationMemoryStore` is
a separate application boundary for conversation turns, attribution references, limits,
idempotency, and TTL. Graph state receives only the current structured `MemoryContext`; it does not
checkpoint the store, locks, service, or complete conversation snapshot.

Each invocation validates and claims the owner, loads memory, resolves safe follow-up context,
executes the ordinary authorized route, and idempotently stores one sanitized turn before final
output. Failed graph executions are not stored. Denied turns contain no evidence references.

## Models and ownership

Schema version `1.0` defines immutable turns, snapshots, evidence references, context, ownership,
write/load results, eviction reports, statistics, and safe inspection. Ownership binds session ID,
user ID, role, permission set, and a deterministic policy fingerprint. Any policy change requires a
new session and fails closed before content is returned.

Evidence memory contains attribution only: IDs, title, source file, section path, type, department,
classification, version, date, and final rank. Bodies, vectors, provider responses, and graph state
are excluded. References are deduplicated and rechecked against centralized authorization.
Historical references only guide a fresh authorized retrieval.

## Bounds, concurrency, and eviction

One lock per session plus a short catalog lock permits independent-session concurrency. Request ID
provides idempotency; changed content under an existing ID is rejected. Limits cover active
sessions, turns, combined characters, evidence references, message sizes, context fields, and TTL.
Oldest turns are evicted atomically until every bound holds; sequences remain monotonic and context
is rebuilt. Expired sessions are removed on access, bounded cleanup, or capacity pressure.

## Context, follow-ups, and sanitization

Deterministic context retains the last question, intent and route; recent titles and IDs; incident
IDs; known service names; departments; document types; evidence IDs; warnings; and turn count. It
creates no prose summary. Conservative patterns resolve prior incidents, a unique runbook, ordinal
results, the same service, previous results, and “again”. Ambiguous references leave the query
unchanged. Evidence bodies are never added.

Before storage, supported bearer tokens, JWT-shaped values, password/API-key/authorization
assignments, and private-key blocks become `[REDACTED]`. UUIDs, incident IDs, service names, and
normal technical terms remain intact. This is a narrow safeguard, not a complete DLP system.

## Failure behavior and limitations

Ownership and integrity failures fail closed. Disabled memory is predictably stateless. A
non-security load failure continues with a warning; an update failure reports that the turn was not
saved without invalidating an otherwise safe answer.

`InMemoryConversationStore` is process-local, lost on restart, not shared between workers, and not
suitable for horizontal scale or long-term records. There is no singleton or import-time task.
Production can replace the protocol with Redis or PostgreSQL using atomic ownership/idempotency,
encryption, retention, and distributed TTL. Future LLM summaries and semantic memory do not exist.

```bash
py -3.12 -m enterprise_ai.graph.cli conversation --role viewer \
  --message "How should payment gateway failover be handled?" \
  --message "Which runbook did you use?"
```
