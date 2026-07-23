# Initial Security Design

The PoC authentication, RBAC/rate limiting, ingestion, retrieval, grounded generation, restricted analysis, recursive research, and privacy-safe tracing boundaries are implemented. Sparse candidates are authorized before scoring; both branches use the same principal and narrowing filters; attribution must agree before fusion. Query text is never parsed as filter syntax.

Session memory binds user ID, role, permissions, and a policy fingerprint. Policy changes require a
new session. Only sanitized public turns and authorized attribution references are retained; no
headers, tokens, evidence bodies, prompts, vectors, or private reasoning are stored.
Structured analysis authorizes before corpus extraction and again before execution. It accepts no
source code, imports, callables, paths, URLs, network, filesystem, environment, or subprocess API.
Retrieved text is untrusted prompt data. Only freshly authorized current-context evidence IDs pass
citation validation; model-generated filenames, line numbers, URLs, and policy changes are ignored.

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

## Implemented PoC identity boundary

- Demonstration usernames and Argon2id password hashes are environment configuration; no plaintext password is stored.
- Login failures are indistinguishable and never log usernames, passwords, hashes, or tokens.
- HS256 JWTs require `sub`, username, role, permissions, issuer, audience, issued/expiry times, and JWT ID. The decoder pins the algorithm and rejects invalid types, roles, permissions, signatures, issuer, audience, and expiry.
- JWT permission claims must exactly equal the centralized server policy for the validated role. Extra, missing, unknown, or incorrectly typed permissions invalidate the token; the JWT is never the final authorization authority.
- Backend policy is the authority: viewer receives knowledge search; analyst adds Python analysis and MCP tools; administrator receives all defined permissions.
- Tool requirements and access levels are immutable mappings. Document authorization requires both a permitted access level and explicit inclusion in `allowed_roles`.

### RBAC permission matrix

| Role | Knowledge search | Python analysis | MCP tools | Administrative tools | Ingestion management | Human approval |
|---|---:|---:|---:|---:|---:|---:|
| Viewer | Allow | Deny | Deny | Deny | Deny | Deny |
| Analyst | Allow | Allow | Allow | Deny | Deny | Deny |
| Administrator | Allow | Allow | Allow | Allow | Allow | Allow |

### Fixed tool requirements

| Tool | Required permission |
|---|---|
| Knowledge search | `knowledge_search` |
| Python analysis | `python_analysis` |
| Employee directory | `mcp_tools` |
| Service catalog | `mcp_tools` |
| Incident records | `mcp_tools` |
| Administrative ingestion | `ingestion_management` |

Unknown tools default to denial and have no inferred permission. Tool parameters cannot alter this mapping.

The MCP host rechecks `mcp_tools` before client construction, discovery, or invocation. Only three
read-only service-data methods are exposed; role, permissions, arbitrary tool names, URLs, paths,
shell syntax, and unexpected properties cannot be tool arguments. Local in-memory/stdio transport
uses the authenticated host as its security boundary and does not claim OAuth. All records are
fictional.

No permission-check HTTP endpoint is exposed. The previously drafted assessment-only route was removed; role and permission behavior is verified directly through the authorization service and integration tests assert the old path returns `404` for anonymous, viewer, analyst, and administrator callers.

### Retrieval access policy

| Role | Permitted access levels |
|---|---|
| Viewer | Public, internal |
| Analyst | Public, internal, confidential |
| Administrator | Public, internal, confidential, restricted |

Access level alone is insufficient: the authenticated role must also appear in the document's validated `allowed_roles`. Missing or malformed metadata fails closed. There is no implicit “all roles” marker in the PoC.

This is not production identity: there is no federation, MFA, refresh/revocation, account lifecycle, lockout, key rotation, asymmetric signing, or distributed token denylist. Production should validate externally issued OIDC tokens from an organizational IdP (for example Entra ID, Keycloak, or Auth0), map trusted groups/claims to internal roles, use managed keys/secrets, and preserve the same backend authorization service.

## Implemented rate-limit boundary

Login buckets use `anonymous:<sha256 fingerprint>` internally; authenticated buckets use the JWT-validated principal UUID, never a bearer token, `X-User-ID`, username, or request parameter. Direct ASGI client host is used by default and raw addresses are neither stored nor logged. `X-Forwarded-For` is accepted only when proxy trust is explicitly enabled, the direct peer is allowlisted, and exactly one valid forwarded IP is present. A network fingerprint can still group NAT users or change with client networks and is only a PoC fallback.

Policy names, capacity, refill, and cost are server configuration. Clients and LLMs cannot select or alter them. Login, standard, and future expensive operations fail closed if enforcement is unavailable. Health probes are unthrottled by design. In-memory state is not a distributed defense; production must move atomic evaluation to Redis and enforce trusted proxy/network topology.

## Synthetic-data safety boundary

The valid corpus contains fictional documents only and is scanned for private-key markers, common API-key/token forms, password assignments, non-placeholder email domains, public-looking IPv4 addresses, and a small real-bank denylist. Nine intentionally malicious but non-executable fixtures are isolated under `data/security_fixtures/`, use a separate manifest, and are excluded from valid ingestion. The scan is lightweight test-data hygiene, not a substitute for production DLP, malware scanning, or legal review. All retrieved content will still be treated as untrusted when retrieval is implemented.

Authenticated chat derives identity only from the verified Bearer token. Its strict body excludes
roles, permissions, trace IDs, routes, tools, namespaces, and retrieval policy. JSON and SSE share
the existing atomic per-user quota and graph/session authorization. CORS uses exact configured
origins; wildcard credentialed origins are invalid. HTTP logs and SSE errors exclude bodies,
tokens, evidence, tool results, prompts, and exception text.

The ingestion parser treats the valid manifest as an allowlist, bounds paths, rejects symlinks/traversal and fixture/glossary paths, verifies body hashes and exact metadata agreement, and uses a duplicate-key-rejecting safe YAML loader. Markdown and fenced code remain inert data. Managed artifacts are validated before a transactional directory swap. These local controls do not replace production malware scanning, DLP, tenant-aware job authorization, encrypted storage, or audit retention.

Research enforces authorization before catalog construction, every retrieval, restricted analysis, aggregation, and citation validation. The compiler rejects authorization/build overrides, arbitrary tools or Python, URLs, paths, cycles, unknown dependencies, and resource violations. Workers receive task-scoped state; models cannot select roles, tools, budgets, namespaces, or graph structure.

Deterministic coverage cannot be overridden by model output. LLM-budget exhaustion prevents provider execution and falls back only to already authorized, attribution-validated evidence; provider prompts, responses, retry internals, and budget locks are never public.

Structured facts have bounded names and values, preserve safe attribution, normalize aware timestamps to UTC, and are reauthorized before conflict creation. Planner repair is limited to one benign correction; security-boundary violations never receive repair and repaired plans cannot bypass compiler limits.

The analytical response boundary ignores provider-authored calculations and renders trusted typed results deterministically. Script, URL, tool, role, scope, identifier, taxonomy, and count alterations therefore cannot reach the response or memory. Insufficient-evidence output reveals no inaccessible titles, IDs, or counts.
## Observability boundary

Trace payloads are constructed from a closed allowlist of bounded scalar metadata. Raw queries, evidence, prompts, provider responses, authorization headers, credentials, user records, and exception representations are excluded. Authorization remains inside retrieval and research services; tracing receives only post-policy counts and statuses and cannot substitute evidence or alter a decision.
