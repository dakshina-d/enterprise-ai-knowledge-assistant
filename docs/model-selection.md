# Model Selection

The configurable real-provider default is `gpt-5.4-mini`. It is selected as a pragmatic modern
starting point for bounded grounded enterprise answers where structured-output reliability,
latency, and cost balance matter more than maximum open-ended reasoning. The application uses the
OpenAI Responses API with a strict Pydantic output schema, `store=false`, low reasoning effort, a
default temperature of `0.1`, bounded output tokens, timeout/retry controls, and explicit provider
closure. These are configuration defaults, not measured claims that the model is universally best.

The model is not claimed to be universally best. Larger frontier models may improve difficult
synthesis at higher latency and cost; smaller models may suit high-volume simple answers but require
evaluation for structured-output and grounding reliability. The context supplied here is bounded to
retrieved chunks or typed analysis results rather than the model's maximum context window.

Change `OPENAI_RESPONSE_MODEL` through deployment configuration, never request input. Production
selection requires representative evaluations for citation validity, abstention, prompt injection,
latency, cost, and role-specific corpus behavior. Standard tests use `FakeLLMProvider`, so they are
deterministic, offline, credential-free, and do not assert prose produced by a live model.

The deterministic fake is also the default for credential-free local and container demos. It
returns typed drafts that exercise graph routing, evidence bounds, citation validation, response
guardrails, fallback, streaming, memory, and trace spans without depending on network availability
or paid API calls.

The provider abstraction deliberately owns only generation. Authentication, RBAC, retrieval
filters, tool authorization, evidence construction, citation validation, deterministic analytical
calculations, public event projection, and memory policy remain application-owned. Changing models
therefore cannot expand a user's access or redefine grounding policy.

Known limitations include possible model hallucination, incomplete semantic entailment, latency and
cost variability, provider outages, prompt sensitivity, and evolving model behavior. The bounded
citation and output validators reduce these risks but do not constitute a universal fact checker or
formal safety proof. No live-model answer-quality score is claimed by this repository.
