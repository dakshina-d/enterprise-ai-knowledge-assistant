# Initial Security Design

This is a preliminary threat list for planned capabilities. The current baseline contains no LLM, retrieval, identity, or tool integration.

| Threat | Intended controls |
|---|---|
| Prompt injection | Separate instructions from user data, validate input, constrain graph transitions, and apply output guardrails. |
| Indirect prompt injection in documents | Treat retrieved text as untrusted, preserve provenance, detect instruction-like content, and prevent it from changing tool policy. |
| Data exfiltration | Enforce least privilege, namespace and metadata filters, response filtering, egress controls, and audit events. |
| Unauthorized retrieval | Apply backend RBAC before querying and enforce tenant/role filters in every retrieval request. |
| Tool misuse | Allowlist tools and arguments, authorize each call, use timeouts and budgets, and record auditable outcomes. |
| Arbitrary Python execution | Use an isolated restricted runtime without host/network/secret access and enforce CPU, memory, and wall-time limits. |
| Secret leakage | Use environment injection or a secrets manager, redact logs, scan commits, and never expose secrets to prompts. |
| Hallucinated citations | Generate citations only from retrieved identifiers and verify every citation against the retrieved evidence set. |
| Denial of service | Validate request size, apply token-bucket limits, bound recursion and concurrency, and set dependency timeouts. |
| Sensitive information in logs | Use structured allowlisted fields, redaction, access controls, retention limits, and no raw prompt logging by default. |

Authentication and production identity integration remain undecided. Demonstration identities, if used, will be visibly marked as proof-of-concept only. Security tests and threat-model revisions will accompany each new trust boundary.
