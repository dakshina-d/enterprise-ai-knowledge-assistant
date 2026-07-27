# Dense Retrieval Design

Status: **Implemented behind explicit, optional Pinecone settings and commands.** Automated tests
use deterministic fakes and require no network. The FastAPI runtime supports local sparse or
Pinecone hybrid retrieval; reranking remains intentionally unimplemented.

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
py -3.12 -m enterprise_ai.retrieval.cli check-index
py -3.12 -m enterprise_ai.retrieval.cli query --role viewer --query "payment failover" --top-k 5
py -3.12 -m enterprise_ai.retrieval.cli evaluate
```

Routine startup and integration verification use `check-index`; they do not re-index an already
compatible current build. Run `bootstrap-index` and `index` only for initial provisioning, when the
configured index is missing, or when the ingestion fingerprint changes:

```bash
py -3.12 -m enterprise_ai.retrieval.cli bootstrap-index
py -3.12 -m enterprise_ai.retrieval.cli index
py -3.12 -m enterprise_ai.retrieval.cli check-index
```

The query CLI is an assessment utility, not authentication. Production callers must supply verified principals. Output contains scores and concise attribution, never vectors, credentials, full provider metadata, or raw restricted bodies.

Requests have configurable timeouts. Only classified transient connection, rate-limit, and server failures receive bounded exponential backoff with deterministic jitter; authentication, validation, authorization, dimension, and metadata failures are permanent. Cancellation propagates. A required failed batch fails indexing. Old builds remain invisible through fingerprint isolation rather than destructive cleanup.

Evaluation selects document-level dense-suitable questions from the committed benchmark and reports recall@1/3/5, MRR, document IDs, authorization/malformed/attribution counts, and latency. Live results are ignored because they are transient. These metrics establish a dense baseline, not answer quality.

## Live integration verification

Use a temporary credential supplied only through the process environment. Never place it in a
tracked file or print it. Confirm the non-secret configuration before running provider commands:

```powershell
$env:PINECONE_API_KEY='<SET_LOCALLY>'
$env:PINECONE_ENABLED='true'
$env:RETRIEVAL_MODE='pinecone_hybrid'
$env:PINECONE_INDEX_NAME='lhcb-knowledge-dev'
$env:PINECONE_NAMESPACE='lhcb-knowledge-dev-v1'
$env:PINECONE_CLOUD='aws'
$env:PINECONE_REGION='us-east-1'
$env:PINECONE_METRIC='cosine'
$env:PINECONE_DENSE_MODEL='llama-text-embed-v2'
$env:PINECONE_DENSE_DIMENSION='1024'

python -c "import os; print('configured' if bool(os.getenv('PINECONE_API_KEY')) else 'missing')"
python -m enterprise_ai.retrieval.cli check-index
```

The committed corpus contains 51 documents and 83 chunks. `check-index` must report the configured
index and namespace, compatible dimension and metric, the current ingestion fingerprint, and at
least 83 current-build records. It must not print credentials, vector bodies, or restricted
document content.

Start the authenticated FastAPI and Streamlit runtime with the same provider selection, then verify:

- A Viewer can answer the active Payment Queue Backlog Recovery Runbook query with grounded
  attribution.
- An Administrator can retrieve the exact identifier `INC-PAY-2025-126`.
- A Viewer requesting that restricted identifier is denied without restricted evidence.
- The unknown identifier `INC-PAY-2099-999` returns no substituted incident.
- Retrieval events report hybrid mode without exposing provider responses or filters.

Provider-failure behavior remains independently reproducible without a live service:

```powershell
python -m pytest -q backend/tests/unit/retrieval/test_dense_retrieval.py
python -m pytest -q backend/tests/unit/retrieval/test_sparse_hybrid.py
python -m pytest -q backend/tests/unit/api/test_runtime_retrieval.py
```

After verification, stop the runtime, remove the temporary `PINECONE_*` variables from the process
environment, and revoke the temporary credential. Do not claim a current live result unless these
checks were actually completed against the configured service.

Manual live verification completed on 2026-07-27 against index `lhcb-knowledge-dev`, namespace
`lhcb-knowledge-dev-v1`, dimension 1024, cosine metric, 83 indexed chunks, and ingestion fingerprint
`65e99b826c8160d59b068035ee4d4b7b663f9c4d93a46b98f4ef5d8e98b38ba5`. Successful runtime checks
covered Viewer hybrid runbook retrieval with attribution, Administrator exact retrieval of
`INC-PAY-2025-126`, Viewer denial without restricted evidence for that identifier, unknown
`INC-PAY-2099-999` without substitution, and normal Viewer runbook retrieval. Deterministic
provider-contract tests remain the reproducible CI evidence. Future live re-verification requires
a temporary credential and Pinecone availability.

## Limitations and next step

Live dimension, index, and evaluation values exist only when explicitly run with valid credentials. Stale records consume storage until a future safely scoped cleanup. Provider metadata limits may require future evidence storage separation. Local BM25 and weighted hybrid fusion are now implemented; reranking remains later evaluated work.
