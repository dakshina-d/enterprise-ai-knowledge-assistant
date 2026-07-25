# Final Submission Checklist

Do not mark manual evidence complete until it has been personally verified after the final commit
and recording.

## Automatically verifiable

- [x] Public repository URL is documented.
- [x] Default branch is `main`.
- [x] Reviewer-oriented README exists.
- [x] Final architecture Markdown and self-contained SVG exist.
- [x] FastAPI JSON/SSE application and health endpoints exist.
- [x] Streamlit chat and Agent Activity Panel exist.
- [x] LangGraph and typed shared state exist.
- [x] Supervisor, Retrieval, Research, and Response agents execute.
- [x] Bounded recursive research executes.
- [x] FastAPI selects local BM25 or real Pinecone dense+BM25 hybrid retrieval by configuration.
- [x] Process-local session memory exists and is ownership-bound.
- [x] Knowledge search, local read-only MCP, and restricted analysis exist.
- [x] Privacy-safe LangSmith adapter and offline trace demonstration exist.
- [x] Viewer/Analyst/Administrator RBAC is backend-enforced.
- [x] Per-user process-local Token Bucket exists.
- [x] Input, evidence, response, and citation guardrails exist.
- [x] Dependency/API/tracing failure tests exist.
- [x] Test and quality workflow exists.
- [x] Dockerfile, Compose, health checks, smoke script, and secure defaults exist.
- [x] Docker build/start/API health/UI health/restart/down lifecycle passes for the final files.
- [x] Assumptions/trade-offs and production gaps are documented.
- [x] Documentation-link checker and focused tests exist.
- [x] Final full local verification passes after all final-phase edits.
- [ ] Final deployment/documentation commit has a green GitHub Actions run.
- [ ] Final `main` worktree is clean after the owner commits and pushes.

## Manually verifiable

- [ ] Record an approximately 45-minute public demonstration.
- [ ] Upload the video and confirm anonymous/public access.
- [ ] Insert the real public video URL into [submission.md](submission.md).
- [ ] Show successful LangSmith hierarchy in the recording.
- [ ] Show a Viewer-denied trace with no unauthorized downstream tool span.
- [ ] Run Pinecone bootstrap/index/check and record one hybrid, exact-ID and restricted-RBAC flow.
- [ ] Confirm Pinecone index `lhcb-knowledge-dev`, namespace `lhcb-knowledge-dev-v1`, dimension
  1024, cosine metric, 83 chunks and current build fingerprint.
- [ ] Confirm no secrets, tokens, password input, private trace URLs, or notifications are visible.
- [ ] Check audio quality, cursor visibility, and screen readability.
- [ ] Test the repository URL in a signed-out/incognito browser.
- [ ] Insert the actual final commit SHA into [submission.md](submission.md).
- [ ] Rehearse the reviewer startup instructions on a clean environment.
- [ ] Confirm the architecture SVG is legible during screen sharing.
- [ ] Rewatch the entire recording before publication.

## Final submission fields

Copy and populate only after the corresponding evidence exists:

```text
Repository: https://github.com/dakshina-d/enterprise-ai-knowledge-assistant
Video: TO BE ADDED AFTER RECORDING
Architecture: docs/final-architecture.md
LangSmith project: enterprise-ai-knowledge-assistant-dev
Final commit: TO BE ADDED AFTER THIS COMMIT IS CREATED
Primary setup command: python -m pip install -e ".[dev]"
Known limitations: Local assessment auth; process-local memory/checkpoints/rate limits; no durable replay, enterprise IdP, remote MCP OAuth, arbitrary Python, HITL, reranking, long-term memory, or persistent feedback.
```
