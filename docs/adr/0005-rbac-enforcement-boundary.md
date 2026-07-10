# ADR 0005: Backend RBAC Enforcement Boundary

- Status: Accepted (foundation implemented; downstream enforcement integrations planned)
- Date: 2026-07-10

## Context

Viewer, analyst, and administrator roles affect document access and tool use. LLM instructions are probabilistic and retrieved documents are untrusted.

## Decision

FastAPI/backend policy code is the sole authorization boundary. It derives identity and scope from verified authentication, applies immutable retrieval namespace/filters before queries, and authorizes every tool plus arguments immediately before execution. LLMs may propose actions but cannot grant roles or weaken filters.

## Alternatives considered

- Prompt-only role instructions: cannot provide deterministic enforcement.
- Frontend-only controls: trivially bypassed.
- Pinecone metadata filters without backend policy: insufficient for tool/session authorization and vulnerable to caller-controlled filters.
- Separate policy service: possible production evolution but unnecessary PoC microservice.

## Consequences

Policy is centralized, testable, and consistently auditable. Every adapter must accept policy-derived scope, and missing policy context fails closed. Demonstration authentication remains explicitly non-production.

## Security implications

This prevents confused-deputy and prompt-injection authorization bypasses. IDOR, role matrix, filter integrity, administrator allowlist, and audit-redaction tests are mandatory.
