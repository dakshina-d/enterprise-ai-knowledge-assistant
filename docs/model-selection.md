# Model Selection

The primary manual-assessment model is **Qwen3-4B-Instruct-2507 Q4_K_M**, served locally through
Ollama as `qwen3:4b-instruct`. `FakeLLMProvider` remains the repository and CI default, while the
OpenAI Responses adapter remains an optional cloud provider.

| Environment | Generation provider |
|---|---|
| CI and deterministic offline tests | `FakeLLMProvider` |
| Local manual assessment | Native Ollama API with `qwen3:4b-instruct` |
| Optional cloud | OpenAI Responses API with `store=false` |

## Selection criteria

The local model fits the observed 15.6 GB assessment hardware, runs CPU-only, has no per-request
fee, keeps retrieved evidence on the local machine, and avoids an external LLM availability
dependency. The Qwen instruct family is oriented toward instruction, agent, and tool workflows and
has future multilingual potential. The model is distributed under Apache 2.0, subject to review of
the exact downloaded artifact and its notices.

Ollama's native `/api/chat` endpoint accepts a JSON Schema derived from the existing
`GroundedAnswerDraft` Pydantic model. Ollama 0.32.3 rejects selected descriptive and upper-bound
schema annotations, so the adapter removes only `title`, `default`, `pattern`, `maxLength`, and
`maxItems` from the generated grammar. It adds a grounded-mode requirement for at least one claim
and supporting evidence ID. Pydantic then enforces every original bound and pattern, followed by
application citation validation and response guardrails. This is not a duplicate response model.

The request uses `stream=false`, `think=false`, temperature zero, a bounded 8,192-token context,
bounded output, and a bounded keep-alive. Graph and SSE activity still stream to the UI while the
schema-constrained model call is non-streaming. Non-empty thinking/reasoning fields and
`<think>...</think>` content are rejected before graph output.

## Measured local evidence

The manually observed environment and direct structured request produced:

- Ollama `0.32.3`;
- model tag `qwen3:4b-instruct`, model ID `0edcdef34593`;
- approximately 2.5 GB quantized download and 3.9 GB observed runtime model memory;
- CPU utilization observed at 100%;
- 8,192-token runtime context;
- 81 output tokens in 11.64 seconds, including 0.13 seconds load time;
- approximately 7.85 output tokens per second;
- valid schema-constrained JSON; and
- an empty `message.thinking` field.

The repository's safe readiness command independently verifies the version endpoint, installed
model, a small grounded-schema request, Pydantic validation, and empty thinking without printing
the prompt or output:

```powershell
python -m enterprise_ai.llm.cli check-ollama
```

## Application-owned policy

The provider owns generation only. FastAPI authentication, RBAC, routing, retrieval filters,
relevance and authorization checks, tool permissions, calculations, citations, public event
projection, memory policy, and deterministic fallback remain application-owned. Changing the model
cannot expand access or redefine evidence policy.

The model is pretrained; it is not trained or fine-tuned on the fictional enterprise corpus.
Documents are parsed, chunked, and indexed for retrieval-augmented generation. Updating documents
requires re-ingestion and re-indexing, not model retraining.

## Honest limitations

Free-text instruction compliance was imperfect in manual testing, so schema-constrained generation
is mandatory. This four-billion-parameter model is smaller than frontier models, CPU generation is
slower, and recursive multi-call research may take several minutes. Retrieval quality still
controls grounding quality, local execution is not automatically production-scalable, and larger
models may improve synthesis at higher memory, latency, and energy cost.

No universal quality claim or formal model benchmark comparison is made. Representative production
selection would require citation, abstention, latency, prompt-injection, fairness, multilingual,
role-isolation, and cost evaluation on governed data.
