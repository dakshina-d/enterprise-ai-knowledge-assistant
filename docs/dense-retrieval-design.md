# Dense Retrieval Design

Status: **Implemented behind explicit, optional Pinecone commands.** Automated tests use deterministic fakes and require no network. No public retrieval endpoint, sparse search, hybrid fusion, reranking, graph, or answer generation is included.

The dependency is `pinecone>=9.0,<10.0`. Pinecone 9 uses built-in `httpx[http2]` async transport and publishes no `asyncio` extra; clean dependency resolution does not install or require `aiohttp`.

## Provider and index

Pinecone Inference generates bring-your-own dense vectors using configurable `llama-text-embed-v2` by default. Documents use `passage` input mode and queries use `query`. Dimension is explicitly configured as 1024 by default, validated against the model's public `supported_dimensions`, sent on every embedding request, and confirmed by a controlled probe before index use. Every vector is non-empty, finite, and dimension-consistent.

A normal dense serverless index allows later sparse vectors on the same deterministic record IDs. Explicit bootstrap creates only an absent index, validates dimension/metric/readiness, uses configured cloud/region, and never deletes or recreates an incompatible index. Cosine is the default. Async clients are closed through service lifecycle and are never created at import or FastAPI startup.

The single `lhcb-knowledge-dev-v1` namespace represents the fictional organization/environment. Roles, access levels, departments, and document types remain metadata, avoiding record duplication and preserving cross-department search.

## Indexing and isolation

`index` validates ingestion artifact hashes, loads all 83 chunks, embeds controlled `search_text`, and preserves `text` as citation evidence. Embedding/upsert batches default to 32/50. Record IDs are deterministic `chunk_id` values. Flat metadata includes identity, attribution, RBAC, ISO/numeric dates, tags/relationships, section/lines, source hashes, content trust, schema version, and ingestion `build_fingerprint`. Metadata size is bounded before provider calls.

Every query includes a server-owned conjunction:

```text
build_fingerprint == current build
AND access_level IN AuthorizationService.allowed_access_levels(principal)
AND allowed_roles contains principal.role
AND validated optional narrowing filters
```

Callers cannot submit raw Pinecone filters, roles, namespaces, or fingerprints. Optional filters support departments, document types, statuses, date bounds, document IDs, tags, and access levels only as a subset of the principal's server-derived allowance.

Provider results are untrusted. Required attribution, hashes, dates, enums, finite score, and current fingerprint are validated locally. `AuthorizationService.is_document_authorized` rechecks access and role membership. Unauthorized or malformed matches are dropped without widening or an unfiltered fallback. Dense cosine scores are separate and unclamped; shared evidence accepts valid values from -1 through 1.

## Operations

```bash
py -3.12 -m enterprise_ai.retrieval.cli bootstrap-index
py -3.12 -m enterprise_ai.retrieval.cli index
py -3.12 -m enterprise_ai.retrieval.cli check-index
py -3.12 -m enterprise_ai.retrieval.cli query --role viewer --query "payment failover" --top-k 5
py -3.12 -m enterprise_ai.retrieval.cli evaluate
```

The query CLI is an assessment utility, not authentication. Production callers must supply verified principals. Output contains scores and concise attribution, never vectors, credentials, full provider metadata, or raw restricted bodies.

Requests have configurable timeouts. Only classified transient connection, rate-limit, and server failures receive bounded exponential backoff with deterministic jitter; authentication, validation, authorization, dimension, and metadata failures are permanent. Cancellation propagates. A required failed batch fails indexing. Old builds remain invisible through fingerprint isolation rather than destructive cleanup.

Evaluation selects document-level dense-suitable questions from the committed benchmark and reports recall@1/3/5, MRR, document IDs, authorization/malformed/attribution counts, and latency. Live results are ignored because they are transient. These metrics establish a dense baseline, not answer quality.

## Limitations and next step

Live dimension, index, and evaluation values exist only when explicitly run with valid credentials. Stale records consume storage until a future safely scoped cleanup. Provider metadata limits may require future evidence storage separation. Local BM25 and weighted hybrid fusion are now implemented; reranking remains later evaluated work.
