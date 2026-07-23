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

For a real smoke test, supply (without committing) `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=<user-provided-key>`, and `LANGSMITH_PROJECT=enterprise-ai-knowledge-assistant-dev`, then run an authorized request and an authorization-denied request. Real LangSmith verification was completed successfully: explicit run IDs matched, unbatched create/update ordering finalized all runs, end times were recorded, parent-child hierarchy was correct, inputs and outputs remained hidden, restricted content and secrets were absent, and denied outcomes appeared as `completion_status=denied` and `route=deny` on both the root and supervisor spans.

Known limitations: the adapter reports safe structural summaries rather than prompt/token detail, and a real SaaS smoke test is not part of offline CI.
