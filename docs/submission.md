# Submission

This document is intentionally incomplete until the final commit and public recording exist.
Placeholders must be updated by the repository owner; they are not evidence.

## Submission fields

| Field | Value |
|---|---|
| Repository URL | `https://github.com/dakshina-d/enterprise-ai-knowledge-assistant` |
| Default branch | `main` |
| Final commit SHA | `TO BE ADDED AFTER THIS COMMIT IS CREATED` |
| Public demo video URL | `TO BE ADDED AFTER RECORDING` |
| Video duration target | Approximately 45 minutes |
| Final architecture | [Final assessment architecture](final-architecture.md) |
| Compliance audit | [Assessment compliance audit](assessment-compliance-audit.md) |
| Requirements traceability | [Requirements traceability](requirements-traceability.md) |
| Assumptions/trade-offs | [Assumptions and trade-offs](assumptions-and-tradeoffs.md) |
| Model rationale | [Model selection](model-selection.md) |
| Demonstration script | [45-minute script](demo-script-45-minutes.md) |
| Demonstration runbook | [Demo runbook](demo-runbook.md) |
| Evidence checklist | [Demo evidence checklist](demo-evidence-checklist.md) |
| Final checklist | [Final submission checklist](final-submission-checklist.md) |
| Local/container setup | [Local and container deployment](local-container-deployment.md) |
| LangSmith project | `enterprise-ai-knowledge-assistant-dev` |

## Test and CI evidence

- GitHub Actions workflow: `.github/workflows/ci.yml`.
- The assignment owner manually confirmed the workflow for hardening commit `575768d` green.
- The final deployment/documentation commit requires its own green run after it is created and
  pushed manually.
- CI runs deterministic corpus, ingestion, sparse retrieval, Ruff, strict MyPy, full Pytest, clean
  tree, documentation-link, and Compose configuration checks without provider credentials.
- Local verification commands are in README and the deployment guide. The final files passed a
  local image build, API/UI startup and health smoke, and teardown; CI intentionally keeps only
  deterministic Compose configuration validation because image construction is network-sensitive.

## LangSmith trace evidence

The project name is safe to publish; individual workspace/run URLs may contain private identifiers
and are not committed. During the recording:

1. inject a temporary `LANGSMITH_API_KEY` at runtime;
2. show one successful root/child hierarchy and one Viewer-denied trace;
3. verify hidden inputs/outputs and safe metadata;
4. confirm the denied trace has no unauthorized MCP/Python span;
5. hide the address bar and all private identifiers; and
6. revoke the key and clear the process environment afterward.

If the service is unavailable, show `python -m enterprise_ai.graph.cli trace-demo --query hello`
and the offline trace tests, and state that the remote manual evidence could not be recorded.

## Implemented mandatory features

- Streamlit multi-turn chat with native POST-SSE consumption and a live Agent Activity Panel.
- FastAPI authentication boundary, Viewer/Analyst/Administrator RBAC, per-user Token Bucket, strict
  validation, safe errors, and structured operational logging.
- LangGraph Supervisor, Retrieval, Research, and Response agents with typed state and singular
  validated terminal output.
- Bounded recursive research, authorized local BM25 plus optional Pinecone dense/hybrid retrieval,
  attribution, citation validation, and deterministic fallback.
- Bounded process-local session memory, three local read-only MCP tools, and restricted typed Python
  analysis.
- Optional privacy-safe LangSmith tracing, direct/indirect prompt guardrails, response policy,
  dependency failure containment, and offline acceptance evidence.
- Local manual generation through Ollama/`qwen3:4b-instruct`; Qwen is pretrained and enterprise
  documents are re-ingested/re-indexed for RAG, never used to retrain the model.
- Verified Viewer retrieval question: `What does the active Payment Queue Backlog Recovery Runbook require for controlled backlog drain and idempotency verification?`

## Bonus status

Implemented bonus:

- Dockerfile and Compose packaging for a local two-service PoC, verified through image build,
  API/UI startup and health checks, and teardown.

Explicitly unimplemented bonus features:

- human-in-the-loop approval;
- reranking;
- durable/long-term memory;
- persistent feedback loop; and
- production deployment infrastructure.

No mandatory status depends on a bonus.

## Known limitations

The system is a bounded executable assessment PoC. Authentication uses local JWT/password
configuration; memory, checkpoints, and rate limits are process-local; stream replay is not
durable; MCP is local/read-only; analysis accepts typed aggregates rather than arbitrary code; live
provider execution needs runtime credentials; citation checks are structural rather than universal
semantic proof; and production identity, shared state, secrets, network controls, telemetry,
retention, governance, horizontal scaling, and approval workflows are absent.

## Reviewer startup

Credential-free infrastructure smoke:

```powershell
docker compose config --quiet
docker compose build
docker compose up -d
python scripts/container_smoke.py
```

This verifies startup/health only because authentication defaults to disabled. Stop with:

```powershell
docker compose down --remove-orphans
```

For interactive assessment, generate ignored local credentials and follow the authenticated section
of [local and container deployment](local-container-deployment.md):

```powershell
python scripts/create_demo_env.py --llm-provider ollama
docker compose --env-file .env.demo up -d --build
python scripts/container_smoke.py
```

The repository owner must add the final commit SHA and public video URL only after those artifacts
exist, then re-run link, secret, clean-tree, CI, and incognito repository-access checks.
