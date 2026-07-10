# Proposed Architecture

Status: **Partially implemented.** Foundations, ingestion, optional Pinecone dense retrieval, local BM25 sparse retrieval, and backend hybrid fusion now run. Reranking, graph, tool, memory, LLM, SSE, and UI integrations remain planned. Pinecone remains explicit and is not initialized during API startup.

## Architectural principles

- Keep the modular monorepo and deploy the PoC as a small number of containers; do not create a microservice per agent.
- FastAPI is the policy-enforcement boundary. LLM output can propose actions but cannot grant authorization.
- Retrieved documents are **untrusted data**. They never become instructions and are validated before entering model context.
- Use async I/O for LLM, Pinecone, MCP, memory, and tool calls; use synchronous code for local validation and deterministic policy checks; use Server-Sent Events (SSE) for one-way streaming; run ingestion offline.
- Emit structured operational summaries, never private chain-of-thought.

## System context (proposed)

```mermaid
flowchart LR
    User[Enterprise user] -->|HTTPS: sync requests and SSE| App[Knowledge assistant]
    Admin[Administrator] -->|HTTPS: ingestion control if enabled| App
    App -->|Async HTTPS| LLM[LLM provider]
    App -->|Async HTTPS| PC[(Pinecone)]
    App -->|Async MCP transport| Ext[MCP server]
    App -->|Restricted job protocol| Py[Restricted Python runtime]
    App -->|Traces| LS[LangSmith]
    Source[Mock documents] -->|Offline ingestion| App
```

External dependencies are the LLM provider, Pinecone, LangSmith, and any separately deployed MCP or restricted-runtime service. The browser never calls them directly.

## Container and component architecture (proposed)

```mermaid
flowchart TB
    subgraph Browser[Browser trust zone]
        UI[Streamlit frontend]
    end
    subgraph Application[Application trust zone]
        API[FastAPI API and SSE]
        Auth[Authentication middleware]
        Rate[Per-user token bucket]
        Validate[Request validation]
        Graph[LangGraph orchestration]
        Agents[Supervisor, retrieval, recursive research, response]
        Tools[Knowledge search, Python analysis, MCP client]
        Guard[Prompt, evidence, citation, brand guardrails]
        Memory[Conversational memory]
        Obs[Structured logging and LangSmith adapter]
    end
    subgraph Data[External data zone]
        Pinecone[(Pinecone hybrid index)]
        MCP[MCP server]
        Python[Restricted Python runtime]
        Provider[LLM provider]
    end
    subgraph Offline[Offline ingestion]
        Ingest[Parse, normalize, chunk, enrich, embed, sparse encode]
    end
    UI --> API --> Auth --> Rate --> Validate --> Graph
    Graph --> Agents --> Tools
    Graph --> Guard
    Graph --> Memory
    Graph --> Obs
    Agents --> Provider
    Tools --> Pinecone
    Tools --> MCP
    Tools --> Python
    Ingest --> Pinecone
```

The Streamlit container owns presentation only. FastAPI owns schemas, identity, authorization, budgets, graph execution, event projection, and error mapping. LangGraph coordinates agent roles; agents do not become independently deployed services. The MCP server is separate only where its tool boundary or lifecycle requires it.

## Request lifecycle (proposed)

```mermaid
sequenceDiagram
    participant U as Streamlit
    participant A as FastAPI
    participant G as LangGraph
    participant D as Dependencies
    U->>A: POST message (synchronous acceptance)
    A->>A: Authenticate, rate-limit, validate
    A-->>U: 202 request_id and events_url
    U->>A: GET event stream (SSE)
    A->>G: Start async graph
    G->>D: Async retrieval, LLM, and authorized tools
    D-->>G: Evidence and bounded results
    G-->>A: Safe lifecycle and token events
    A-->>U: SSE status, tool, retrieval, and token events
    G->>G: Validate evidence, citations, and output
    A-->>U: response.completed or response.failed
```

Health and session reads are synchronous HTTP operations. Message processing is asynchronous after acceptance. Tokens and safe agent activity are streaming operations. Ingestion is offline and never runs in the interactive request path.

## Trust boundaries (proposed)

```mermaid
flowchart LR
    B[Browser] -->|TB1: untrusted input and bearer/session token| F[FastAPI policy boundary]
    F -->|TB2: minimized prompt, no credentials| L[LLM provider]
    F -->|TB3: authorized namespace and metadata filter| P[(Pinecone)]
    F -->|TB4: allowlisted tool and arguments| M[MCP server]
    F -->|TB5: constrained job, no host secrets| R[Restricted Python runtime]
    P -->|TB6: untrusted retrieved documents| V[Evidence validation]
    V -->|validated evidence only| L
```

| Boundary | Required controls |
|---|---|
| Browser → FastAPI | TLS, authentication, CSRF/session controls as applicable, schema and size validation, per-user rate limits, safe errors. |
| FastAPI → LLM provider | Secret isolation, egress allowlist, timeout/retry budget, minimized prompts, provider data-retention configuration. |
| FastAPI → Pinecone | Server-side credentials, role-derived namespace/filter, timeout, result validation, audit metadata. |
| FastAPI → MCP server | Tool allowlist, per-call authorization, argument schema, timeout, output validation, transport authentication. |
| Application → restricted Python runtime | No arbitrary host execution, immutable image, resource/time limits, no secrets or network by default, sanitized data transfer. |
| Retrieved documents → model context | Treat as untrusted data, enforce access filters first, detect instructions, delimit content, preserve provenance, validate citations. |

## Deployment topology (proposed)

```mermaid
flowchart TB
    subgraph LocalPoC[PoC Docker Compose or local processes]
        UI[Streamlit container]
        API[FastAPI container]
        MCP[MCP container]
        PY[Restricted Python container]
        MEM[(PoC session store)]
    end
    User -->|HTTPS via local reverse proxy| UI
    UI -->|Private HTTP| API
    API --> MCP
    API --> PY
    API --> MEM
    API -->|TLS| Pinecone[(Pinecone SaaS)]
    API -->|TLS| LLM[LLM provider]
    API -->|TLS| LangSmith[LangSmith]
```

The implemented PoC token bucket uses per-bucket async locks and bounded opportunistic TTL cleanup. It is process-local, resets on restart, and cannot coordinate multiple workers. Production should use an atomic Redis Lua script or equivalent transaction plus a managed identity provider, distributed session storage, secrets manager, network policies, horizontally scalable API workers, durable event/session persistence, isolated analysis jobs, and centralized telemetry.

## Responsibility summary

Authentication middleware establishes identity; RBAC maps identity to roles and scopes; the token bucket protects per-user capacity; request validation normalizes safe inputs. LangGraph routes simple questions to retrieval and complex questions to bounded recursive research. The knowledge-search tool performs authorized hybrid retrieval, while Python and MCP calls require separate authorization. Conversational memory supplies bounded session context. Guardrails inspect input, untrusted evidence, citations, and final responses. LangSmith records traces and structured logging records allowlisted operational fields. SSE projects only safe public events to the UI.

Detailed contracts are in [graph design](graph-design.md), [retrieval design](retrieval-design.md), [API contracts](api-contracts.md), [event stream design](event-stream-design.md), and [error handling](error-handling-design.md).
