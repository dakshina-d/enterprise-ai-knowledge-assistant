# ADR 0006: Bounded Fan-out/Fan-in Recursive Research

- Status: Accepted (bounded PoC implementation complete)
- Date: 2026-07-10

## Context

Complex questions may require decomposition and evidence from multiple independent subquestions. An unconstrained recursive agent risks runaway cost, latency, unsafe tools, and corrupted shared state.

## Decision

Use an explicit planner with bounded fan-out/fan-in workers. The default maximum depth is 2 (hard maximum 3), batch concurrency is at most 4, and every request has time, token, retrieval, and tool budgets. Workers receive immutable parent snapshots and return typed local envelopes. A deterministic aggregator merges validated successes and records failed subtasks as warnings.

## Alternatives considered

- Ordinary top-k RAG for every query: lower cost but inadequate for genuine multi-part research.
- Unbounded autonomous recursion: flexible but unsafe and unpredictable.
- Sequential decomposition only: simpler state but higher latency and poor failure isolation.
- External distributed workflow: stronger durability but excessive PoC complexity.

## Consequences

Complex research becomes observable, parallel, and partially recoverable, at the cost of graph and budget-management complexity. Simple questions remain on ordinary retrieval. Budget exhaustion may yield an honest partial result.

## Security implications

Each worker inherits—not expands—authorization. All tools are reauthorized per call. Worker results are treated as untrusted until validated; one worker cannot mutate principal, policy, sibling state, or final response. Operational summaries replace hidden reasoning.
