# ADR 0002: LangGraph as the Orchestrator

- Status: Accepted (bounded PoC implementation complete)
- Date: 2026-07-10

## Context

The assistant needs explicit routing, bounded recursion, parallel research, tool authorization checkpoints, retries, memory updates, human approval, and observable terminal states.

## Decision

Use LangGraph inside the FastAPI backend as the workflow orchestrator. Define typed state, allowlisted conditional routes, isolated worker state, deterministic reducers, and explicit budgets. Agents remain logical roles, not microservices. Expose structured operational summaries rather than private chain-of-thought.

## Alternatives considered

- Imperative async service code: fewer dependencies but harder to inspect, checkpoint, and test as paths grow.
- Autonomous agent loop: flexible but insufficiently bounded and auditable.
- External workflow engine: durable and scalable but excessive operational scope for the PoC.

## Consequences

Graph paths and state transitions become testable and traceable, with some framework coupling and state-schema migration cost. Ordinary requests use a short path; recursion is opt-in and bounded.

## Security implications

LLM output cannot select arbitrary nodes or bypass backend authorization. Identity and policy fields are immutable. Tool calls, evidence, retries, recursion, time, and tokens are bounded and audited.
