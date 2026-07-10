# Synthetic Sample-data Design

## Purpose and disclaimer

This deterministic corpus supports future retrieval, metadata filtering, citation, recursive research, incident analysis, authorization, and injection-resistance evaluation. **Lanka Horizon Commercial Bank is fictional. All people, incidents, systems, dates, metrics, and identifiers are synthetic and must not be interpreted as information about any real financial institution.** No retrieval, chunking, embedding, Pinecone, graph, or LLM feature is implemented by this dataset commit.

## Distribution

| Document type | Count |
|---|---:|
| Policy | 7 |
| Architecture | 8 |
| Runbook | 9 |
| Incident | 16 |
| Product specification | 6 |
| Meeting note | 5 |
| **Total** | **51** |

| Department | Count |
|---|---:|
| Payments | 17 |
| Digital banking | 7 |
| Cybersecurity | 6 |
| Infrastructure | 5 |
| Operations | 5 |
| Risk and compliance | 4 |
| Customer service | 4 |
| Data and analytics | 3 |

| Access level | Count |
|---|---:|
| Public | 2 |
| Internal | 17 |
| Confidential | 25 |
| Restricted | 7 |

Role allowance appears in 18 viewer, 44 analyst, and all 51 administrator records. The internal AI Assistant Usage Policy deliberately excludes viewers, proving that access level alone is insufficient; both access level and explicit `allowed_roles` must authorize future retrieval.

## Dates, incidents, and recurring causes

The fixed benchmark period is 2025-07-01 through 2026-06-30. Sixteen incidents fall between 2025-07-03 and 2026-06-27; thirteen involve payment failure or degradation. Recurring categories include connection-pool exhaustion, message-queue backlog, database lock contention, and capacity-planning error. Single-event categories cover certificate lifecycle, configuration drift, retry storm, third-party timeout, DNS/service discovery, deployment regression, monitoring gap, and manual operational error.

The incidents intentionally use lexical variants such as “connection pool saturation,” “exhausted JDBC connection pool,” and “connection slots unavailable.” Similar symptoms sometimes have different causes, and the same cause sometimes produces different symptoms.

## Relationships and authority

There are 87 validated cross-document references. Incidents reference active runbooks and policy; runbooks reference architecture and policy; product specifications reference architecture and control requirements; meeting notes discuss incidents, proposals, and corrective actions.

Authority descends from approved policies, final architecture, active runbooks, post-incident-final reports, approved product specifications, then meeting notes/drafts. The corpus includes one superseded policy, one draft architecture proposal, one archived runbook, and a meeting proposal explicitly rejected in favor of final architecture.

## Retrieval and research challenges

Exact challenges include incident IDs, service names, error-family terminology, titles, and runbook names. Semantic challenges describe pending transfers, intermittent failure, accumulating messages, unavailable connection slots, and degraded customer journeys. Metadata challenges combine department, document type, access, role, date, and status. Twelve benchmark questions include simple lookup, hybrid retrieval, filtered retrieval, unauthorized access, source-authority conflict, structured incident analysis, and at least five cross-document tasks. The historical “last year” question is anchored to the fixed benchmark period rather than wall-clock time.

## Security fixture separation

Nine malicious-test-only fixtures live under `data/security_fixtures/` with a separate manifest. They include safe, non-executable injection, override, exfiltration, tool-abuse, fake-citation, malformed metadata, missing access, unknown role, and broken-reference cases. They are never included in the valid manifest.

## Generation and validation

```text
py -3.12 scripts/generate_sample_documents.py
py -3.12 scripts/generate_sample_documents.py --check
py -3.12 scripts/validate_sample_documents.py
```

UUIDv5 identifiers derive from stable slugs. Files and manifests have deterministic ordering. `content_hash` is SHA-256 over the normalized Markdown body only, excluding YAML front matter. The generator safely removes obsolete Markdown only inside its six managed type directories. Check mode performs no writes and detects missing, stale, or obsolete outputs.

The validator independently checks front matter, enums, UUID/date/role fields, uniqueness, manifest coverage, body hashes, broad word-count floors, relationships, portable paths, evaluation references, fixture separation, a small real-organization denylist, and obvious credential/sensitive-data patterns. This lightweight scan is test-data hygiene, not a complete DLP product.

## Limitations

The corpus uses templated prose and intentionally simplified fictional metrics. It is designed for repeatability and evaluation coverage, not legal, regulatory, operational, or banking advice. Authority scoring, parsing, chunking, retrieval, citation validation, and answer evaluation remain future work.
