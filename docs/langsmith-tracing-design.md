# LangSmith tracing design

## Architecture and configuration

The application owns a small recorder abstraction instead of depending on global tracing state. `SafeTracer` is a no-op by default, accepts an offline fake, or delegates to a LangSmith client configured with hidden inputs and outputs. `LANGSMITH_TRACING=true` requires `LANGSMITH_API_KEY`; project, endpoint, workspace, and application environment are typed settings. The secret uses Pydantic's secret type and is never attached to metadata.

## Hierarchy

Each invocation starts one `enterprise_ai_assistant` root. Stable children cover supervisor, retrieval, research, restricted Python analysis, response, citation validation, and memory. Research adds plan, worker, aggregation, evidence aggregation, conflict analysis, and coverage spans. Worker spans carry safe task identifiers, parent task identifier, depth, and round so concurrent recursive work remains understandable.

Manual spans are intentional. Automatically wrapping the OpenAI client or serializing LangGraph state could export raw questions, prompts, evidence, or unvalidated drafts. LangGraph still receives a safe run name, tags, and metadata for local execution configuration, but application-owned spans define the exported privacy boundary.

The custom recorder assigns every LangSmith run explicitly with the SDK's `id=` keyword and uses that same ID for updates and child `parent_run_id` values. Automatic batching is intentionally disabled for this manual recorder so a parent create completes before any child create or run update. Synchronous LangSmith create, update, and flush calls run in worker threads and are awaited, preserving create/update ordering without blocking the asyncio event loop. This is an intentional correctness and graceful-failure trade-off.

Span metadata can be enriched before completion through the same allowlisted sanitizer used at span start. Root traces add the final application completion status, route, and safe outcome flags; supervisor traces add their routing decision and only record a terminal completion status when they establish one. LangSmith technical success remains distinct from application `completion_status`: an authorization denial is a successfully completed trace whose metadata records `completion_status=denied` and `route=deny`.

## Metadata and privacy

Only allowlisted scalar values are retained, strings are limited to 256 characters, and keys are emitted deterministically. The schema includes application/graph versions, environment, role, safe correlation IDs, route, permission count, planner version, retrieval mode, task hierarchy, bounded counts, budget/coverage/completion/citation/fallback statuses, model, and build fingerprint.

Raw queries, prompts, evidence, vectors, restricted titles or IDs, authorization material, cookies, JWTs, API keys, provider responses, private reasoning, exception messages, and stack traces are never accepted. Authorization runs in the existing services and cannot be bypassed by recorder failure. Viewer-denied requests expose only safe route and status information.

## Failure, cancellation, and concurrency

Recorder start, finish, and flush exceptions are isolated from graph state, output, events, memory, and authorization. Application failures are represented by exception class name only. External cancellation is marked and re-raised. A `ContextVar` maintains async task-local parentage, including concurrent research workers; tests prove separate invocations do not share roots.

## Verification

Run `python -m enterprise_ai.graph.cli trace-demo --query "hello"` for an offline fake-recorder summary. It prints enabled state, configured project, root name, child count, and final status without content or credentials.

For a current live integration check, privately configure:

```powershell
$env:LANGSMITH_TRACING='true'
$env:LANGSMITH_API_KEY='<SET_LOCALLY>'
$env:LANGSMITH_PROJECT='enterprise-ai-knowledge-assistant-dev'
python -c "import os; print('configured' if bool(os.getenv('LANGSMITH_API_KEY')) else 'missing')"
```

Start the authenticated local runtime and issue representative requests:

- Viewer retrieval: ask what the active Payment Queue Backlog Recovery Runbook requires.
- Analyst analysis: ask to count payment incidents by root cause.
- Analyst MCP: ask who owns the `payment-gateway` service.
- Analyst research: compare pending payment status in September with delayed settlement in
  February.
- Viewer denial: request the restricted disaster-recovery topology.

In the private LangSmith project, verify one finalized `enterprise_ai_assistant` root per request,
explicit parent/child relationships, route-specific spans, finalized end times, and allowlisted
metadata containing only roles, routes, counts, safe identifiers, and outcome flags. Inputs and
outputs must remain hidden; prompts, evidence, private reasoning, credentials, raw exceptions, and
restricted content must be absent. A denial should be a technically successful trace with
`completion_status=denied` and `route=deny`.

Stop the runtime after verification, remove `LANGSMITH_API_KEY` and related tracing variables from
the process environment, and revoke the temporary credential.

Manual live verification completed on 2026-07-27 for Viewer retrieval, Analyst structured Python
analysis, Analyst MCP execution, bounded recursive research, prompt-injection/security denial, and
controlled Ollama unavailability with deterministic fallback. The verified traces contained
route-specific hierarchy and privacy-safe metadata without prompts, raw evidence, credentials,
private reasoning, or raw provider exceptions. Offline fake-recorder tests remain the reproducible
CI evidence. Future re-verification depends on a temporary credential and LangSmith availability.

Known limitations: the adapter reports safe structural summaries rather than prompt/token detail,
and a real SaaS integration check is not part of offline CI.
