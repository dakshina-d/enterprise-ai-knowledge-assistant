# Proposed Retrieval Design

Status: **Ingestion, Pinecone dense retrieval, deterministic local BM25 sparse retrieval, mandatory
RBAC filtering, and transparent weighted hybrid fusion are implemented. Bonus reranking is not
implemented.** Retrieved provider metadata, local sparse artifacts, and documents are untrusted
data. See [dense retrieval design](dense-retrieval-design.md) and
[sparse/hybrid design](sparse-and-hybrid-retrieval-design.md).

## Offline ingestion

```mermaid
flowchart LR
    F[Allowlisted files] --> P[Parse by file type]
    P --> N[Normalize text and structure]
    N --> C[Structure-aware chunking]
    C --> M[Enrich and validate metadata]
    M --> H[Compute content hash]
    H --> D[Dense embedding]
    H --> S[Sparse representation]
    D --> U[Pinecone batch upsert]
    S --> U
    U --> V[Count and sample verification]
```

The source dataset contains 51 Markdown documents with YAML front matter and SHA-256 body hashes. The manifest is provider neutral and contains no vectors or Pinecone fields. Security fixtures and the glossary are outside the allowlisted inputs. Implemented stages through content hashing emit deterministic JSONL records described in [ingestion design](ingestion-design.md); embedding and upsert remain proposed.

Parsing rejects non-allowlisted, malformed, hash-mismatched, traversing, and symlinked inputs.
Normalization preserves structure and source lines while removing unstable formatting.
Structure-aware chunks use configurable approximate-token limits and bounded overlap.
Deterministic hashes, UUIDv5 identifiers, and a build fingerprint support drift detection. Local
sparse term weights/artifacts and optional dense embedding, batch upsert, namespace querying, and
stale-vector deletion reconciliation are implemented; live Pinecone execution remains explicit and
credential-dependent.

## Metadata schema

| Field | Type | Purpose |
|---|---|---|
| `document_id` | string | Stable source-document identifier. |
| `chunk_id` | string | Stable versioned chunk identifier. |
| `title` | string | User-visible document title. |
| `source` | string | Safe source locator or display label. |
| `department` | string | Organizational ownership/filter. |
| `document_type` | enum/string | Policy, report, guide, and similar classification. |
| `access_level` | enum | Coarse classification such as public, internal, restricted. |
| `allowed_roles` | list of role enums | Defense-in-depth role allowlist. |
| `created_date` | ISO date | Source creation date. |
| `updated_date` | ISO date | Source update date. |
| `version` | string | Source version. |
| `section` | string | Section heading/path. |
| `chunk_index` | integer | Deterministic order within a version. |
| `content_hash` | string | Integrity, idempotency, and duplicate key. |

All enumerated metadata is normalized against a controlled vocabulary. Raw confidential metadata is not returned to the UI or logs.

## Namespaces and authorization filters

The PoC namespace strategy is one namespace per logical corpus/environment, for example `assessment-dev-org`. Tenant separation, if added, must use distinct namespaces or indexes rather than role-only filtering. Document type, department, access level, allowed roles, version, and dates remain metadata filters.

The backend derives a mandatory authorization predicate from the authenticated principal. The client and LLM cannot supply or weaken it. The retrieval adapter combines it with validated user filters using logical AND, sends it to Pinecone on every dense/sparse query, and rechecks every returned record. Unauthorized records are discarded and raise a security audit signal. Only revalidated, authorized evidence can enter model context.

## Deterministic sparse relevance and abstention

After authorization and before evidence enters model context, local sparse retrieval normalizes
query terms, removes instruction-only words and stop words, and separates specific terms from
generic corpus vocabulary. Evidence must cover the query's salient terms using terms that actually
contributed to the BM25 match: one- or two-term queries require complete support and longer queries
require at least half. Generic-only and out-of-vocabulary queries abstain. When the question asks
for current or approved material, archived, draft, and superseded records are deterministically
demoted without being erased from conflict-oriented queries.

This gate is sparse-specific. It does not impose exact lexical overlap on authorized dense/hybrid
semantic evidence. Hybrid fusion retains provider-specific evidence and strips sparse diagnostics
when mapping to the shared dense evidence contract.

The corpus contains no password-policy source; incidental security boilerplate mentioning
passwords is not equivalent policy evidence. Therefore `Summarize the password policy.` now
returns insufficient evidence instead of citing unrelated policies. The demonstration uses the
committed active Payment Queue Backlog Recovery Runbook question documented in the README.

## Query and ranking pipeline

1. Normalize the query without changing its intent.
2. Resolve immutable namespace and mandatory role/access filters.
3. Produce dense query embedding and sparse query representation asynchronously.
4. Retrieve an expanded candidate set with Pinecone hybrid scoring.
5. Normalize scores, fuse rankings, deduplicate, and enforce per-document diversity.
6. Optionally rerank the small authorized candidate set.
7. validate untrusted content and attach evidence identifiers.
8. Return a bounded evidence set to the graph.

### Hybrid-ranking decision

| Approach | Advantages | Trade-offs |
|---|---|---|
| Weighted score combination | Single tunable `alpha`; natural fit for Pinecone hybrid vectors; efficient one-query PoC; preserves magnitude. | Dense/sparse score calibration matters; tuning can be corpus-specific. |
| Reciprocal Rank Fusion (RRF) | Robust to incomparable score scales; simple rank-based behavior. | Usually requires separate result lists, more requests/candidates, and discards score magnitude. |

**Decision:** use weighted score combination for the PoC, with an evaluation-set-tuned but configuration-controlled `alpha`. Record dense, sparse, and fused scores internally. Production may adopt RRF if evaluation shows unstable calibration across corpora or embedding upgrades. Optional reranking is a later bonus and operates only after authorization.

## Evidence, attribution, and defenses

Each evidence object carries `document_id`, `chunk_id`, safe title/source, section, version, content hash, retrieval scores, and exact text span. Citations use opaque evidence IDs assigned to the request, never model-invented URLs.

- **Unauthorized chunks:** server-derived namespace/filter before retrieval, post-query policy recheck, fail-closed on missing metadata.
- **Duplicate dominance:** collapse identical content hashes; cap chunks per document/section; use overlap-aware near-duplicate checks and diversity selection.
- **Hallucinated citations:** citation validator accepts only request evidence IDs and verifies claim support; unknown IDs trigger one repair or failure.
- **Unused evidence citations:** response generation records claim-to-evidence use; final validation removes unsupported/unused references and requires regeneration when material.
- **Malicious document instructions:** label and delimit evidence as untrusted data, scan for injection indicators, never permit retrieved text to alter policy/tools, and exclude or quarantine unsafe chunks while retaining an audit reason.

Retrieval quality tests will measure authorization precision (required 100%), citation validity, recall at k, nDCG/MRR where appropriate, duplicate rate, latency, and regression against a versioned mock query set.
