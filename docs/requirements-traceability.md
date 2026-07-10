# Requirements Traceability

“Implemented” means executable and presently verified in this baseline. Every AI, retrieval, security-feature, and bonus row remains “Planned.”

| Requirement | Priority | Planned component | Verification method | Current status | Demo evidence |
|---|---|---|---|---|---|
| Repository scaffolding | Must | Repository root | Tree review | Implemented | Modular directory walkthrough |
| Documentation | Must | `docs/` | Content review | Implemented | Architecture, security, ADR, and plans |
| Health endpoints | Must | Backend API | Automated endpoint tests | Implemented | `/health/live` and `/health/ready` responses |
| Logging foundations | Must | Backend core | Ruff, MyPy, unit inspection | Implemented | JSON formatter output |
| Streamlit chat | Must | Frontend | UI and integration test | Planned | Disabled placeholder only |
| Multi-turn conversation | Must | Graph and memory | Conversation integration test | Planned | Future multi-turn scenario |
| Streaming responses | Must | API and frontend | Streaming integration test | Planned | Future token stream capture |
| Live agent activity | Must | Graph, API, and frontend | Event-stream UI test | Planned | Placeholder panel only |
| FastAPI | Must | Backend API | Startup and API tests | Planned | Health-only baseline exists; assistant API pending |
| Async APIs | Must | Backend API | Async integration tests | Planned | Future request concurrency test |
| Async retrieval | Must | Retrieval | Async contract tests | Planned | Future concurrent retrieval trace |
| Async tool execution | Must | Tools | Timeout/concurrency tests | Planned | Future parallel tool trace |
| Structured logging | Must | Observability | Log schema and capture tests | Planned | JSON foundation exists; request/agent events pending |
| LangGraph | Must | Graph | Graph topology and execution tests | Planned | Proposed flow diagram |
| Supervisor agent | Must | Agents | Routing scenario tests | Planned | Future LangSmith trace |
| Retrieval agent | Must | Agents | Retrieval scenario tests | Planned | Future attributed answer |
| Research agent | Must | Agents | Tool-use scenario tests | Planned | Future research trace |
| Response agent | Must | Agents | Synthesis scenario tests | Planned | Future grounded response |
| RLM decomposition | Must | Graph | Complex-query decomposition test | Planned | Future decomposition trace |
| Recursive sub-analysis | Must | Graph | Bounded-recursion tests | Planned | Future depth/budget trace |
| Hybrid dense and sparse retrieval | Must | Retrieval | Relevance evaluation | Planned | Future evaluation report |
| Pinecone namespaces | Must | Retrieval and ingestion | Namespace isolation test | Planned | Future index inspection |
| Metadata filtering | Must | Retrieval and security | Filter enforcement tests | Planned | Future role-filtered query |
| Document attribution | Must | Retrieval and response | Citation provenance tests | Planned | Future source-linked response |
| Session memory | Must | Memory | Multi-turn isolation tests | Planned | Future session replay |
| Knowledge search tool | Must | Tools and retrieval | Tool contract tests | Planned | Future tool-call trace |
| MCP tool | Must | MCP server and tools | MCP contract/authorization tests | Planned | Future constrained MCP call |
| Python analysis tool | Must | Tools | Sandbox and resource-limit tests | Planned | Future isolated analysis |
| LangSmith traces | Must | Observability | Trace presence/schema check | Planned | Future trace link |
| Prompt-injection protection | Must | Security | Adversarial evaluation | Planned | Future blocked prompt case |
| Input validation | Must | API and security | Invalid payload tests | Planned | Future validation response |
| Retrieved-content validation | Must | Retrieval and security | Malicious-document tests | Planned | Future quarantined content |
| Tool authorization | Must | Security and tools | Role/tool matrix tests | Planned | Future denied tool call |
| Hallucinated-citation protection | Must | Security and response | Fabricated-citation tests | Planned | Future rejected citation |
| Brand-safety validation | Must | Security and response | Policy evaluation suite | Planned | Future guarded output |
| Viewer role | Must | Security | RBAC integration tests | Planned | Future read-only scenario |
| Analyst role | Must | Security | RBAC integration tests | Planned | Future analytics scenario |
| Administrator role | Must | Security | RBAC integration tests | Planned | Future admin scenario |
| Token-bucket rate limiting | Must | Security and API | Burst/refill tests | Planned | Future 429 and recovery |
| LLM failure handling | Must | Services and graph | Provider fault-injection test | Planned | Future graceful fallback |
| Vector-database failure handling | Must | Retrieval | Pinecone fault-injection test | Planned | Future degraded response |
| MCP failure handling | Must | MCP server and tools | MCP fault-injection test | Planned | Future bounded failure |
| Tool timeout handling | Must | Tools | Timeout tests | Planned | Future timeout event |
| Invalid-request handling | Must | API | Validation/error contract tests | Planned | Future structured 4xx response |
| Human-in-the-loop bonus | Bonus | Graph and frontend | Interrupt/resume test | Planned | Future approval checkpoint |
| Reranking bonus | Bonus | Retrieval | Comparative relevance evaluation | Planned | Future metrics comparison |
| Long-term memory bonus | Bonus | Memory | Persistence/privacy tests | Planned | Future cross-session recall |
| Feedback-loop bonus | Bonus | Frontend and observability | Feedback persistence test | Planned | Future feedback record |
| Docker Compose bonus | Bonus | Deployment | Clean-environment smoke test | Planned | Future multi-service startup |
