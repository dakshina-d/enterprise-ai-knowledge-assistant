# ADR 0001: Modular Monorepo Project Structure

- Status: Accepted
- Date: 2026-07-10

## Context

The assessment spans an API, user interface, ingestion workflow, constrained MCP server, shared engineering standards, and architecture evidence. The initial team and deployment topology are small, while trust boundaries and future scaling concerns still need to remain visible.

## Decision

Use a modular monorepo with separated `backend`, `frontend`, `ingestion`, and `mcp_server` components. Use a `src` layout for Python packages and keep cross-component documentation and tooling at the repository root. Backend packages reserve cohesive boundaries for API, agents, graph, retrieval, tools, memory, security, observability, models, services, and core foundations.

## Consequences

One repository makes atomic changes, local setup, shared quality gates, and assessment review straightforward. Explicit component directories discourage UI/backend coupling and allow later extraction into independently deployed services. The trade-off is shared repository lifecycle and the need to guard against accidental cross-component imports. Component-specific packaging and deployment configuration will be introduced only when those components gain implementation.

## Alternatives considered

- Multiple repositories: stronger lifecycle isolation, but premature operational and review overhead.
- One undifferentiated application package: initially simpler, but obscures trust boundaries and encourages coupling.
