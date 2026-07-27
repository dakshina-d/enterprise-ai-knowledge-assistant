# Final Assessment Architecture

Status: **Implemented bounded assessment PoC with optional external integrations.**

The diagram distinguishes executable local components from optional provider adapters and
process-local state. The FastAPI boundary owns identity, authorization, quotas, routing inputs,
tool permissions, and public error/event projection. Neither the browser, retrieved documents, nor
an LLM can grant permissions.

![Final assessment architecture](assets/final-architecture.svg)

## Renderable Mermaid source

```mermaid
flowchart TB
    classDef implemented fill:#e8f2ff,stroke:#245b9e,color:#10243e
    classDef local fill:#fff4d6,stroke:#9a6700,color:#3f2b00
    classDef optional fill:#f1e8ff,stroke:#6f42a8,color:#2e174d,stroke-dasharray:5 4
    classDef offline fill:#e7f7ed,stroke:#267346,color:#123b25
    classDef untrusted fill:#ffe8e8,stroke:#a33a3a,color:#4d1717

    subgraph BROWSER["Browser trust boundary"]
        USER["Enterprise user<br/>untrusted input"]:::untrusted
        UI["Streamlit chat UI<br/>multi-turn chat<br/>Live Agent Activity Panel"]:::implemented
        USER --> UI
    end

    subgraph POLICY["FastAPI policy boundary"]
        API["FastAPI<br/>JSON + native POST SSE"]:::implemented
        AUTH["Authentication<br/>Viewer / Analyst / Administrator RBAC"]:::implemented
        LIMIT["Per-user Token Bucket<br/>request validation"]:::implemented
        SAFE["Safe error mapping<br/>structured logging"]:::implemented
        API --> AUTH --> LIMIT
        API --> SAFE
    end
    UI -->|"Bearer + strict JSON<br/>safe public events"| API

    subgraph PROCESS["Application process — process-local PoC state"]
        GRAPH["LangGraph + typed graph state"]:::local
        SUP["Supervisor agent"]:::implemented
        RET["Retrieval agent<br/>runtime mode selector"]:::implemented
        RES["Research agent<br/>bounded recursive planning"]:::implemented
        RESP["Response agent"]:::implemented
        FAIL["Safe failure handler<br/>failed GraphOutput"]:::implemented
        MEMORY["Bounded session memory<br/>in-memory checkpoint"]:::local
        GUARD["Input/evidence/output guardrails"]:::implemented
        CITE["Citation validation"]:::implemented
        GRAPH --> SUP
        SUP --> RET
        SUP --> RES
        RET --> RESP
        RES --> RESP
        RESP --> CITE
        GRAPH --> FAIL
        FAIL --> CITE
        GRAPH <--> MEMORY
        GRAPH --> GUARD
    end
    LIMIT --> GRAPH

    subgraph TOOLS["Tool authorization boundary"]
        SEARCH["Knowledge search<br/>exact-ID + RBAC constraints"]:::implemented
        MODE{"RETRIEVAL_MODE"}:::implemented
        HYBRID["Pinecone hybrid mode<br/>application-owned fusion"]:::implemented
        DENSE["Pinecone dense adapter<br/>namespace + metadata filters"]:::optional
        SPARSE["Local BM25 sparse store"]:::implemented
        MCP["Three local read-only<br/>MCP enterprise-data tools"]:::local
        PY["Restricted typed<br/>Python analysis"]:::local
        SEARCH --> MODE
        MODE -->|"sparse"| SPARSE
        MODE -->|"pinecone_hybrid"| HYBRID
        HYBRID --> DENSE
        HYBRID --> SPARSE
    end
    RET --> SEARCH
    SUP --> MCP
    SUP --> PY

    subgraph EXTERNAL["Optional external provider boundary"]
        OPENAI["OpenAI Responses API<br/>optional; store=false"]:::optional
        PINECONE["Pinecone service<br/>optional"]:::optional
        LANGSMITH["LangSmith<br/>optional safe metadata"]:::optional
    end
    subgraph LOCALMODEL["Local generation boundary"]
        OLLAMA["Native Ollama API<br/>Qwen3-4B-Instruct<br/>schema constrained"]:::local
        FAKE["Deterministic fake provider<br/>CI/tests default"]:::offline
    end
    RESP --> OLLAMA
    RESP --> OPENAI
    RESP --> FAKE
    DENSE --> PINECONE
    GRAPH -. "allowlisted root/node/tool/provider spans" .-> LANGSMITH

    subgraph INGEST["Offline pipeline"]
        CORPUS["Synthetic organizational corpus"]:::offline
        PIPE["Parse / validate / chunk / index<br/>RAG; no model retraining"]:::offline
        ARTIFACTS["Committed retrieval artifacts<br/>untrusted document content"]:::untrusted
        CORPUS --> PIPE --> ARTIFACTS
    end
    ARTIFACTS --> SPARSE
    ARTIFACTS --> DENSE
    GUARD -. "validate before model context" .-> ARTIFACTS
```

## Trust and deployment notes

- The Streamlit browser session is presentation-only. It cannot supply roles, permissions, routes,
  namespaces, filters, tools, or policy.
- FastAPI derives identity from the validated bearer token in authenticated local mode and applies
  RBAC again at retrieval and tool boundaries.
- Retrieved text is untrusted data. Authorization, integrity, instruction-content, and citation
  checks occur before final response completion.
- MCP and restricted analysis are local application boundaries, not separately deployed remote
  services. No OAuth-enabled remote MCP service is claimed.
- Session memory, LangGraph checkpointing, and rate-limit buckets are process-local and reset when
  the API container restarts.
- Local manual assessment uses native Ollama with `qwen3:4b-instruct`; CI and infrastructure smoke
  use the deterministic fake provider. OpenAI, Pinecone, and LangSmith remain disabled unless the
  reviewer explicitly selects them and supplies required runtime credentials.
- Qwen is pretrained. Enterprise documents are indexed for RAG; updating them requires
  re-ingestion/re-indexing, not model retraining.
- `RETRIEVAL_MODE=sparse` constructs only the local BM25 adapter.
  `RETRIEVAL_MODE=pinecone_hybrid` requires enabled Pinecone configuration and constructs the real
  Pinecone dense branch plus local BM25 fusion in the FastAPI runtime. Live provider proof remains
  credential-dependent.
- Offline ingestion creates the committed artifacts used by local retrieval; it is not part of the
  interactive container request path.
