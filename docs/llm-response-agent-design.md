# Grounded LLM Response Agent

Status: **implemented** with an application-owned provider protocol, an offline fake, and the
official asynchronous OpenAI Responses API provider. OpenAI mode uses structured Pydantic parsing,
`store=False`, no provider tools, no previous response, zero SDK retries, explicit timeout, and a
bounded application retry policy. No client is created at module import.

## Grounding and prompts

Prompt versions are `1.0` for grounded retrieval, structured analysis, and direct modes. Evidence
is ranked deterministically and mapped from bounded identifiers (`E1`, `E2`, …) to current
application evidence. The model sees title, authority metadata, section, line range, and a bounded
chunk excerpt—not vectors, hashes, permissions, JWT claims, or graph state. Evidence is delimited as
untrusted data and instructions explicitly prohibit following document instructions, revealing
hidden instructions, changing authorization, or executing tools.

Defaults cap evidence at 8 items, 24,000 total characters, and 4,000 per item; prompts at 32,000;
answers at 8,000; citations at 20; output at 1,500 tokens; and repair at one attempt. Request input
cannot override model, provider, storage, prompt, or limits.

## Structured claims and validation

The provider returns `GroundedAnswerDraft`, containing a summary, bounded typed claims, warnings,
and insufficiency/clarification flags. Factual claims require structured supporting IDs. The backend
then verifies every ID is in the current context, is authorized, belongs to the current ingestion
build, has valid attribution and line range, and stays within citation bounds. Source metadata is
always rendered from application objects. This structural validation does not prove semantic
entailment; production evaluation and later claim-level guardrails remain necessary.

An invalid citation receives at most one repair using exactly the same evidence. A still-invalid or
unsafe draft becomes a deterministic evidence-list fallback; invalid content is never exposed. No
authorized evidence produces a deterministic insufficiency response without calling the provider.
Analysis answers use the provider boundary but render the typed calculation deterministically to
prevent numerical or categorical drift.

## Graph, memory, and streaming

Graph version `1.1` adds `generate_response` and `validate_citations` between retrieval/analysis and
output preparation. Denials, unsupported routes, and direct greetings remain deterministic. Safe
generation and citation events contain counts/status only. Memory receives only the validated final
answer and verified attribution already present in graph evidence—not prompts, drafts, failed
citations, provider objects, or reasoning.

Unvalidated model tokens are intentionally not streamed. A future SSE layer may stream activity
immediately and split only the final validated answer into bounded chunks. Recursive research, MCP,
human approval, LangSmith, a final prompt-injection classifier, and a full brand-validation layer
remain unimplemented.
