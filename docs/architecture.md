# Proposed Architecture

This document describes the intended architecture. Except for the FastAPI health baseline, JSON logging, configuration, and Streamlit placeholder, these components are not implemented.

## Proposed high-level architecture

```mermaid
flowchart LR
    User[Enterprise user] --> UI[Streamlit UI]
    UI --> API[FastAPI API]
    API --> Security[Validation, RBAC, rate limits, guardrails]
    Security --> Graph[LangGraph supervisor]
    Graph --> Agents[Retrieval, research, response agents]
    Agents --> Retrieval[Hybrid retrieval service]
    Retrieval --> Pinecone[(Pinecone namespaces)]
    Agents --> Tools[Authorized async tools]
    Tools --> MCP[Constrained MCP server]
    Tools --> Python[Sandboxed analytics]
    Graph --> Memory[Session memory]
    Graph --> Observability[Structured logs and LangSmith]
    Ingestion[Document ingestion] --> Pinecone
```

The API will own trust-boundary enforcement and orchestration. Streamlit will remain a presentation client and will not duplicate authorization, retrieval, or agent logic. Ingestion will validate, normalize, chunk, and index mock organizational documents. The MCP service will expose a deliberately narrow tool surface.

## Proposed preliminary LangGraph flow

```mermaid
flowchart TD
    Start([Validated request]) --> Supervisor[Supervisor agent]
    Supervisor --> Decompose[RLM decomposition]
    Decompose --> RetrievalAgent[Retrieval agent]
    Decompose --> ResearchAgent[Research agent]
    RetrievalAgent --> Validate[Validate retrieved content]
    ResearchAgent --> Authorize[Authorize tool calls]
    Validate --> Recursive{More sub-analysis?}
    Authorize --> Recursive
    Recursive -- Yes, bounded --> Decompose
    Recursive -- No --> ResponseAgent[Response agent]
    ResponseAgent --> Guardrails[Citation and brand-safety validation]
    Guardrails --> Stream[Stream response and activity]
    Stream --> End([Persist session turn])
```

Cycles will be bounded by depth, time, and token budgets. Authorization will be deterministic backend code, not an LLM instruction. Retrieved content will be untrusted and isolated from system instructions. Failure paths, timeouts, and human review points will be added as the corresponding features are implemented.
