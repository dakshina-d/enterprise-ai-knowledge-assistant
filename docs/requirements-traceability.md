# Requirements Traceability

This is the concise status index. The requirement-by-requirement evidence, demo steps, and
limitations are in the [assessment compliance audit](assessment-compliance-audit.md). Runtime code
and tests, not design prose, are the source of truth.

Statuses are strict: **Implemented** means executable and verified; **Implemented for bounded PoC**
means executable with the stated local/offline limitation; **Partial** means a mandatory part is
missing; **Not implemented** means no executable feature; **Bonus/not required** is outside the
mandatory assessment.

| Requirement area | Status | Implementation | Primary verification | Limitation |
|---|---|---|---|---|
| Streamlit chat, multi-turn, streaming, Activity Panel | Implemented for bounded PoC | `frontend/enterprise_ai_frontend`, `frontend/streamlit_app.py` | `frontend/tests` | No durable replay, cross-device history, or token refresh |
| FastAPI async JSON/SSE API | Implemented for bounded PoC | `enterprise_ai.api` | `backend/tests/integration/test_chat_api.py`, `test_chat_sse.py` | Process-local runtime and state |
| Structured HTTP/graph logging | Implemented for bounded PoC | `core/logging.py`, `api/errors.py`, `api/sse.py`, `graph/runtime.py` | API logging tests; `test_assessment_guardrails.py`; `test_assessment_failure_matrix.py` | No external log pipeline/retention policy |
| LangGraph orchestration and typed state | Implemented | `enterprise_ai.graph` | graph unit/integration suites | In-memory checkpointer; deterministic routing |
| Supervisor, retrieval, research, response agents | Implemented for bounded PoC | graph nodes/routing, retrieval, research, response service | graph, research, grounding, role acceptance suites | Agents are logical graph boundaries, not services |
| Bounded recursive research/RLM concept | Implemented for bounded PoC | `enterprise_ai.research` | research unit/integration/evaluation suites | Typed bounded decomposition, not unrestricted recursion |
| Dense Pinecone retrieval | Implemented for bounded PoC | `retrieval/dense_retriever.py`, Pinecone gateway | dense retrieval/provider suites | Live execution is explicit and credential-dependent |
| Sparse BM25 and hybrid fusion | Implemented | `retrieval/sparse`, `retrieval/hybrid` | sparse/hybrid suites and CLI validation | Offline benchmark defaults to local sparse |
| Namespace, metadata, attribution, local RBAC recheck | Implemented | retrieval filters/models/authorization | dense/hybrid authorization and citation suites | One configured corpus namespace in the PoC |
| Session conversational memory | Implemented for bounded PoC | `enterprise_ai.memory` | memory and API role acceptance suites | Process-local, bounded, non-durable |
| Knowledge search | Implemented | retrieval graph routes/services | graph retrieval and role acceptance suites | Not a caller-selectable arbitrary tool |
| MCP enterprise data | Implemented for bounded PoC | `enterprise_ai.mcp_tools` | MCP protocol/security/failure suites | Three local read-only fictional tools; no OAuth |
| Restricted Python analysis | Implemented for bounded PoC | `tools/python_analysis` | Python tool and role acceptance suites | Typed aggregates only; no arbitrary code |
| LLM abstraction, fake/OpenAI, grounding, citations, fallback | Implemented for bounded PoC | `enterprise_ai.llm` | grounded-response, citation, failure-matrix suites | Fake default; live OpenAI opt-in |
| LangSmith tracing | Implemented for bounded PoC | `observability/tracing.py` and graph spans | offline fake hierarchy/failure suites; documented prior remote smoke | Current remote export is a manual credentialed check |
| Prompt/evidence/output guardrails | Implemented for bounded PoC | `security/guardrails.py`, graph/grounding/aggregation checks | `test_assessment_guardrails.py`, citation/security suites | Bounded deterministic patterns, not a universal content classifier |
| Authentication and Viewer/Analyst/Administrator RBAC | Implemented for bounded PoC | security services and API dependencies | authentication, authorization, role acceptance suites | Demo JWT/password identities; no enterprise IdP |
| Token-bucket rate limiting | Implemented for bounded PoC | `enterprise_ai.rate_limit` | rate-limit unit/API suites | Atomic only within one process |
| Graceful dependency/API/cancellation failures | Implemented for bounded PoC | typed service and transport boundaries | assessment failure matrix plus retrieval/MCP/Python/API/tracing suites | No distributed circuit breaker |
| Representative fictional corpus and evaluation | Implemented | `data/sample_documents`, `data/evaluation` | deterministic generator/validator/ingestion/research CLIs | Synthetic assessment data only |
| Human-in-the-loop | Bonus/not required | None | N/A | Not implemented |
| Reranking | Bonus/not required | None | N/A | Not implemented |
| Long-term memory | Bonus/not required | None | N/A | Not implemented |
| Persistent feedback loop | Bonus/not required | None | N/A | Not implemented |
| Docker Compose/deployment packaging | Implemented for bounded PoC | `Dockerfile`, `compose.yaml`, smoke and demo-env scripts | Compose config plus local image build, API/UI health smoke, and teardown | Local two-service proof only; no production orchestration or CI runtime gate |
| Final architecture and submission evidence | Implemented documentation | final architecture, assumptions, demo, runbook, evidence, submission/checklist documents | Offline documentation-link check | Video URL and final commit SHA remain manual |

The implementation is not claimed production-ready. Production requires organizational OIDC,
shared rate/session/checkpoint stores, durable replay, managed secrets, deployment-specific network
controls, isolated remote tool execution where needed, and operational monitoring.
