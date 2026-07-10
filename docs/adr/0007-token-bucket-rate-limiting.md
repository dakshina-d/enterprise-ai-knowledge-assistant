# ADR 0007: Process-local Token-bucket Rate Limiting

- Status: Accepted (PoC implementation complete; distributed store planned)
- Date: 2026-07-10

## Context

Login abuse and authenticated request bursts require deterministic backend limits before expensive assistant capabilities exist. Route code must not depend on a particular storage technology.

## Decision

Use fixed, settings-validated token-bucket policies with an injected monotonic clock and async atomic store protocol. The in-memory PoC store holds available tokens and refill/last-seen timestamps, evaluates `min(capacity, available + elapsed * refill_rate)`, and serializes each bucket with its own async lock. Login keys contain a SHA-256 network fingerprint; authenticated keys contain only the validated user UUID. Bounded opportunistic TTL scanning removes inactive state and locks without background tasks.

Default policies are login `(5, 1/30 per second, cost 1)`, standard `(30, 0.5 per second, cost 1)`, and expensive `(10, 1/15 per second, cost 2)`. The expensive contract is not attached until AI/tool endpoints exist. Enforcement failures fail closed; health endpoints remain unthrottled.

## Alternatives considered

- Fixed window: simpler but permits boundary bursts and has coarse retry behavior.
- Leaky bucket: smooth output but less natural for configured burst capacity.
- SlowAPI or middleware package: convenient but obscures identity/order and store replacement requirements.
- Redis now: production-suitable coordination but unnecessary infrastructure for this assessment phase.
- Background cleanup: predictable cadence but introduces task lifecycle and test-leak complexity.

## Consequences

Tests can advance time without sleeping, concurrent requests cannot overspend one process, and route dependencies remain store-neutral. State resets on restart and each worker owns independent limits. Production replaces the store with Redis using one atomic Lua script or equivalent transaction for refill, deduction, TTL, and retry calculation.

## Security implications

JWT validation precedes user-bucket selection; invalid tokens cannot consume another user's bucket. Clients and LLMs cannot choose keys, cost, or policy. Proxy headers are ignored unless a directly connected allowlisted proxy supplies exactly one valid address. Fingerprints avoid raw-address storage but retain NAT/collision/privacy limitations. Public errors and headers contain no keys, addresses, fingerprints, tokens, locks, or store state.
