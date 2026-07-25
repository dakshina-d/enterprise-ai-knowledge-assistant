# Sparse and Hybrid Retrieval Design

Status: **Implemented and connected to FastAPI runtime selection.** Local deterministic BM25
indexing and authorized sparse retrieval run fully offline. Pinecone hybrid mode concurrently
combines the Pinecone dense branch with BM25. Pinecone credentials are required only when
`RETRIEVAL_MODE=pinecone_hybrid`. Reranking is not implemented; graph routing and grounded answer
generation consume the shared retrieval result.

## Why local BM25

The 83-chunk proof-of-concept corpus is small enough for a transparent repository-owned lexical index. This avoids adding a service or BM25 dependency while making exact identifiers, error codes, service names, acronyms, and policy titles explainable. A production deployment may migrate the same contracts to Pinecone sparse vectors, OpenSearch, Elasticsearch, or another managed lexical service after scale and operations are evaluated.

The analyzer applies NFC, whitespace normalization, and Unicode case-folding. It retains words, numbers, mixed alphanumeric values, underscores, and complete hyphenated identifiers. Hyphenated and underscore identifiers additionally emit their direct components without combinatorial expansion. No stemming is used because exact technical names matter and dense retrieval covers semantic variation. No stop words are removed; this preserves negation and domain terms. Analyzer version `1.0` and stop-word decision `none-1.0` participate in the fingerprint.

## BM25 and artifacts

For query term `t` and chunk `d`, the implementation uses:

```text
idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
score(t,d) = idf(t) * tf(t,d) * (k1 + 1)
             / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))
```

Repeated query terms contribute deterministically. Defaults are `k1=1.5` and `b=0.75`. Zero scores are omitted and ties use ascending chunk ID. Scores remain full-precision, finite, and non-negative.

`bm25_index.json` stores sorted document lengths/term frequencies and document frequencies; it does not duplicate evidence text. `bm25_manifest.json` stores versions, parameters, ingestion/chunk fingerprints, counts, average length, vocabulary size, sparse fingerprint, and index hash. Both are compact UTF-8 canonical JSON with a final newline and no timestamps or machine identity. Build, byte comparison, and validation commands manage only these two files.

## Authorization and attribution

Sparse candidates are resolved only from validated `chunks.jsonl`. Before scoring, `AuthorizationService` enforces the principal's access levels and required membership in `allowed_roles`; typed department/type/status/date/document/tag filters can only narrow. Stale artifacts fail validation. Evidence retains the original chunk `text`, IDs, source lines, hashes, RBAC metadata, ingestion fingerprint, and sparse fingerprint.

Dense and sparse branches receive the same principal, query, filters, and bounded overfetch. They run concurrently with separate timeouts. Scores are normalized independently per query using min-max; a non-empty equal-score branch assigns `1.0` to every present candidate, while missing-branch contributions are `0.0`. Defaults normalize configured weights to dense `0.65` and sparse `0.35`:

```text
hybrid = normalized_dense * dense_weight + normalized_sparse * sparse_weight
```

Raw dense/sparse and normalized values are all retained. Candidates merge by chunk ID. Matching candidates must agree on evidence/document IDs, title, path, section lines, hash, build fingerprint, and RBAC metadata or fusion fails safely. Ordering is hybrid, normalized dense, normalized sparse, raw dense, raw sparse (all descending), then chunk ID ascending.

If exactly one ordinary dependency branch fails and partial results are enabled, the safe branch returns `partial_success` with a warning and failed-branch name. Both failures fail the request. Authorization failures never become partial fallback and queries never become provider filter syntax.

## Evaluation and limitations

Sparse evaluation is deterministic except for console latency and measures document-level recall@1/3/5, MRR, attribution, malformed results, and authorization violations. Hybrid evaluation uses the same benchmark but requires Pinecone. These are retrieval metrics, not answer-quality proof. The fixed weights are not tuned against the full benchmark, avoiding hidden overfitting. Future work may evaluate a managed lexical service and a separate reranking layer.
