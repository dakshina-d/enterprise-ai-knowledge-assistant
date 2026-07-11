# Model Selection

The configurable default is `gpt-5.4-mini`. It is selected as a pragmatic starting point for
bounded grounded enterprise answers where structured-output reliability, latency, and cost balance
matter more than maximum open-ended reasoning. The application uses the Responses API with a strict
Pydantic schema and performs authorization and citation validation itself.

The model is not claimed to be universally best. Larger frontier models may improve difficult
synthesis at higher latency and cost; smaller models may suit high-volume simple answers but require
evaluation for structured-output and grounding reliability. The context supplied here is bounded to
retrieved chunks or typed analysis results rather than the model's maximum context window.

Change `OPENAI_RESPONSE_MODEL` through deployment configuration, never request input. Production
selection requires representative evaluations for citation validity, abstention, prompt injection,
latency, cost, and role-specific corpus behavior. Standard tests use `FakeLLMProvider`, so they are
deterministic, offline, credential-free, and do not assert prose produced by a live model.
