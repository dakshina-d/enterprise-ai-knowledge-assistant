# Assumptions and Trade-offs

## Assignment assumptions

- The committed corpus is entirely synthetic and describes the fictional Lanka Horizon Commercial
  Bank. No real customer, employee, bank, or production data is required or present.
- The source repository and demonstration are intended to be public, so credentials, private trace
  URLs, and screenshots containing tokens remain external.
- Local Argon2id/JWT authentication is sufficient to demonstrate the three assessment roles. It is
  not an enterprise identity system.
- Optional OpenAI, Pinecone, and LangSmith credentials are supplied only at runtime by the
  evaluator and are never required by CI.
- The deterministic fake provider is the authority for repeatable tests and the credential-free
  demo path. It proves contracts and control flow, not live-model prose quality.
- Live Pinecone execution is optional because it requires a provisioned index and credential. The
  local BM25 path and fake dense-provider tests demonstrate mandatory retrieval controls offline.
- LangSmith live tracing is demonstrated separately with a temporary runtime credential. Offline
  fake-recorder tests remain the reproducible privacy/hierarchy evidence.
- The approximately 45-minute public recording and its public URL are manual deliverables created
  after repository changes are finalized.

## Architectural trade-offs

| Decision | Why it fits the assessment | Cost or limitation |
|---|---|---|
| Modular monolith, not a microservice per agent | Keeps policy, types, tests, and local startup coherent | Components do not scale independently |
| FastAPI as non-bypassable policy boundary | Browser/model inputs cannot grant identity, route, tool, or data scope | All interactive traffic depends on one API boundary |
| LangGraph state machine over free-form autonomy | Typed routes, bounded transitions, and singular terminals are auditable | Less open-ended agent behavior |
| Native POST SSE over WebSocket | One-way activity/results fit HTTP auth, proxies, and simple clients | No bidirectional session channel or replay |
| Local BM25 plus optional Pinecone dense retrieval | Credential-free baseline with a realistic dense adapter | Main offline demo is sparse-first |
| Application-owned hybrid fusion | Scores, authorization, attribution, and partial failure remain inspectable | No learned reranker |
| Bounded recursive research | Demonstrates decomposition and fan-out under depth/task/time/call budgets | Not unrestricted recursive model execution |
| Typed restricted analysis | Deterministic aggregates without arbitrary host code | Fixed operation taxonomy |
| Local read-only MCP | Demonstrates official protocol, schemas, RBAC, timeouts, and provenance safely | No remote transport/OAuth |
| Process-local memory/checkpoints | Simple reproducible multi-turn behavior | Lost on restart; unsuitable for multiple API workers |
| Process-local Token Bucket | Concurrent atomicity is demonstrable without infrastructure | No cross-process/user-cluster coordination |
| Deterministic guardrails plus validation | LLM text cannot own policy, evidence authorization, tools, or citations | Pattern rules are bounded, not universal moderation |
| Fake provider in CI | Fast, offline, deterministic, and free of secret/network dependency | Does not measure live model quality |
| Privacy-safe trace metadata | Preserves hierarchy and outcomes without exporting prompts/evidence | Less content is available for trace debugging |

## Production gaps

Production deployment would require:

- enterprise OIDC, MFA, token revocation, lifecycle controls, and managed signing keys;
- distributed memory and LangGraph checkpoint storage;
- Redis-compatible atomic rate limiting;
- durable event storage and replay;
- a managed secrets system and credential rotation;
- ingress/TLS, network policies, egress allowlists, and workload identities;
- authenticated remote MCP transport where organizational services require it;
- isolated analysis workers with operating-system/container resource enforcement;
- horizontal scaling, dependency health/readiness, and graceful rollout behavior;
- centralized production logs, metrics, alerts, traces, retention, and access controls;
- data classification, deletion, retention, DLP, malware scanning, and audit policies;
- formal model, prompt, retrieval, red-team, fairness, and quality governance;
- human approval for genuinely risky actions; and
- measured reranking and semantic answer-quality evaluation where justified.

These omissions are acceptable for a bounded executable assessment because the repository proves
the required control boundaries, behavior, failure contracts, and reproducible offline evidence
without pretending to supply organizational infrastructure. The PoC must not be deployed with real
enterprise data or described as production-ready.
