# Bounded recursive research design

Graph 1.2 implements the project's RLM interpretation as application-owned orchestration, not arbitrary recursive model calls. An authorization-filtered metadata catalog feeds a strict structured planner. Python validates, normalizes, deduplicates and deterministically IDs tasks before execution.

The coordinator is a compiled `StateGraph`. Its conditional dispatcher returns one task-scoped `Send("research_worker", ...)` for each validated task. Worker outputs accumulate through an explicit reducer before deterministic aggregation. A process-local semaphore bounds active workers; cancellation propagates through graph execution. Aggregation validates narrower gap proposals and dispatches later rounds through the same executable `Send` path until sufficient, maximum depth, task budget, or another server-owned limit terminates recursion.

Worker results fan into immutable typed results. Aggregation deduplicates chunks, retains deterministic task provenance and best rank, and caps count/characters. Structural conflict detection conservatively identifies version and lifecycle-status conflicts; it does not claim semantic contradiction detection. Deterministic coverage checks report sufficient, partial, insufficient or budget-exhausted research and preserve gaps and partial failures.

The parent graph routes cross-document requests through research and then reuses the existing evidence validation, grounded response, citation repair/validation, memory and finalization nodes. Final model-facing evidence IDs are therefore assigned only from the final authorized ledger. Supported analysis tasks invoke only the restricted typed Python tool after immediate authorization and atomic budget consumption. Typed calculations, supporting incident IDs, document IDs, taxonomy and algorithm versions remain distinct from document citations and are rendered deterministically. Memory receives the existing bounded verified answer/evidence representation, never worker state, prompts, locks or raw provider output.

Security boundaries apply before catalog construction, on every retrieval, during aggregation and citation validation. Plans cannot contain role/namespace overrides, arbitrary tools, Python, URLs or file paths. The fake planner and BM25 path require no credentials or network access.

The offline `evaluate` command runs the committed 12-question set through the compiled parent graph with the fake planner, BM25, recursive orchestration, restricted analysis, evidence aggregation, grounded fake generation, bounded citation repair, final citation validation, memory update, and no credentials. It reports per-question task, call, evidence, conflict, coverage, final-response, citation, provenance, fallback, and gap measures plus aggregate Recall@1/3/5 and MRR. Retrieval context availability remains separate from citation validity. The citation pass-rate denominator is final rendered factual claims; safe limitation-only answers with no factual claims are excluded. See [research evaluation](research-evaluation.md).

Coverage is deterministic application-owned Python. It consumes zero LLM calls, cannot initiate tools or retrieval, and runs inside the total research deadline. The shared per-invocation LLM allowance counts initial planning, final synthesis, and each application-level citation repair; started calls remain consumed after timeout or cancellation. Exhaustion before synthesis or repair selects a deterministic authorized-evidence fallback instead of exposing an unvalidated draft.

Current limitations: conflict and coverage checks are conservative and primarily structural;
complete semantic contradiction detection is not claimed. Research plan, worker, aggregation,
conflict, and coverage boundaries emit safe spans when tracing is enabled. MCP, FastAPI JSON/SSE,
and Streamlit integration are implemented. Durable distributed workers, human approval,
reranking, durable long-term memory, and persistent feedback are not implemented.

Structured conflicts use an explicit enum of incident timestamps/duration, policy dates, owners, departments, teams, and component/service mappings. Aware timestamps normalize to UTC; naive or malformed values and invalid incident ranges fail validation. Facts are authorization-filtered before comparison, and approved/active metadata wins preference without hiding authorized disagreements. This is deterministic structured comparison, not general semantic entity resolution.

The planner receives at most one repair attempt for benign validation failures such as dependencies or cycles. Unsafe role/access overrides, paths, URLs, arbitrary tools, shell commands, and Python are non-repairable. Repair consumes one shared LLM unit and the corrected plan passes the complete compiler again before any worker dispatch.

Analytical prose is always rendered from the typed Python result; provider prose cannot change counts, categories, identifiers, row scope, taxonomy, algorithm, operation, or formula. Empty evidence skips normal generation and produces a deterministic insufficient-authorized-evidence response with no citations. One-sided and authorization-blocked research remains partial or insufficient without revealing inaccessible metadata.

Compiled-graph stream tests exercise the same `GraphRuntime.astream()` bridge used by the
implemented FastAPI SSE transport. They assert one terminal response, one final output, monotonic
invocation-local sequences, unique event IDs, consistent correlation IDs, task/depth/round worker
payloads, and safe allowlisted metadata.

The live event stream is transient and is not copied into conversation memory. Checkpointed activity history is bounded to the newest 200 validated events; conversation memory retains only the bounded final turn and verified reference contract.

`GraphRuntime.astream()` is the application-owned public event boundary. Its event sequence is schema-validated, correlated, bounded, monotonic and terminally singular. Parallel worker activity is synthesized in deterministic post-fan-in result order and does not represent transport-time completion order. Final aggregation sorts task results and evidence independently of completion timing. True live delivery, downstream disconnect behavior, and replay are deferred to the mandatory FastAPI/SSE integration; this feature adds no callback, sink, bus, or transport abstraction.

The supervisor, retrieval worker, research coordinator, and response service have separate responsibilities: the supervisor selects the authorized route; workers perform task-scoped retrieval and optional typed analysis; the coordinator compiles `Send` fan-out, enforces child/depth/task/retrieval/analysis/evidence/LLM/time budgets, aggregates reducers, conflicts and deterministic coverage; the response service generates only from the final authorized ledger, validates/repairs citations once, and falls back deterministically. Planner repair is limited to one server-controlled structured repair and cannot expand roles, tools, namespaces, budgets or graph topology.

Coverage may end as sufficient, partially sufficient, insufficient, blocked by authorization, budget exhausted, or failed. Cancellation propagates without inventing successful terminal work; planner, worker and total deadlines use bounded typed failure behavior. Conflict detection is structural and authority-aware, not full semantic contradiction detection, general entity resolution, or automatic extraction of every fact.
