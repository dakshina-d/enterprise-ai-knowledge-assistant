# Deterministic Ingestion Design

Status: **Implemented for the local Markdown corpus.** The pipeline parses, normalizes, chunks, enriches, validates, and writes provider-neutral artifacts. It performs no embedding, indexing, retrieval, or network access.

## Command and boundaries

```bash
py -3.12 -m enterprise_ai_ingestion build
py -3.12 -m enterprise_ai_ingestion check
py -3.12 -m enterprise_ai_ingestion validate
```

`build` computes and transactionally replaces the three managed files in `data/processed/`; unrelated files are preserved. `check` recomputes expected bytes without writing and reports drift. `validate` verifies the existing artifact set.

The valid source manifest is the sole allowlist. Absolute paths, traversal, symlinks, files outside `data/sample_documents`, the glossary, security fixtures, duplicate identities/paths, malformed or unsafe YAML, metadata disagreement, and body-hash mismatch fail closed. YAML is parsed as data and Markdown code fences are never executed. Parsing uses bounded asynchronous scheduling around local file work and restores manifest order before downstream processing.

## Normalization and chunking

Normalization is UTF-8/NFC and conservative: line endings, trailing whitespace, excess blank lines, and simple heading/list spacing are canonicalized while headings, lists, tables, code fences, Unicode, and source-line provenance remain intact. The operation is idempotent.

The versioned regex estimator supplies deterministic approximate counts of Unicode words, identifiers, and punctuation without a model provider. These are explicitly not model-token counts. The estimator handles ordinary prose and incident/service identifiers consistently, and its name and version participate in the build fingerprint.

Chunking maintains heading paths on structural blocks while keeping citation text as source content. Adjacent paragraphs, lists, and other compatible blocks are packed first within a section. Small sibling sections may then merge in source order under their document parent when the result remains within the target/maximum and the complete contiguous source range is included. A final small section group is moved as a unit to rebalance the last two chunks; headings, list items, tables, and code fences are not split merely to meet a target. Oversized blocks alone use deterministic sentence/lexical splitting. Empty, heading-only, duplicate, avoidably undersized, and search-context-dominated chunks fail validation.

Defaults remain target 450, maximum 650, overlap 75, and minimum 80 approximate tokens. Target is a soft packing boundary and maximum is hard. A chunk below minimum is permitted only when it is the complete source document; the current corpus needs no exception. Overlap is copied only from the immediately preceding core when both sides remain in the same section and the new core already reaches the target. It never crosses documents or section boundaries and is not added to small residuals.

For the current 51-document corpus, the resulting 83 chunks have minimum 216, mean 336.83, median 315, p75 373, p90 483, p95 495, and maximum 497 approximate tokens. No chunk is below 80 and no corpus chunk contains overlap. Documents produce one or two chunks (median two). This is a substantially less fragmented provider-neutral representation, but retrieval quality has not been proven; relevance and citation evaluation remain required after a retrieval implementation exists.

Chunk and evidence identifiers are UUIDv5 values derived from versioned algorithm inputs, document identity, normalized content, position, and relevant metadata. Material content/configuration/version changes therefore change the build fingerprint and affected identifiers; identical inputs produce byte-identical outputs regardless of configured parsing concurrency.

## Artifact contract

- `documents.jsonl` contains one document record per manifest entry, including authority/access metadata, normalized content hash, source provenance, and chunk counts.
- `chunks.jsonl` contains ordered retrieval-ready text records with exact document metadata, section path, source line range, overlap count, content hash, chunk ID, and evidence ID.
- `ingestion_manifest.json` records schema/algorithm versions, configuration, corpus/build fingerprints, counts, and SHA-256 hashes for both JSONL artifacts.

JSON uses sorted keys, compact separators, UTF-8, and LF endings. Output is staged in the destination parent and swapped only after validation succeeds, so an invalid source or failed build cannot partially replace the prior managed artifact set.

## Limitations

The token count is a lexical approximation and differs from provider tokenization. Markdown parsing is deliberately narrow rather than CommonMark-complete. Merged chunks cover one exact, contiguous source-line interval and include every intervening block; the pipeline refuses merges that would require discontinuous citation spans. Source spans for an individually split multiline oversized block remain conservative. Search text adds a short title/type/department/section context outside citation `text`; it is validated not to dominate the body. Local filesystem replacement is not a distributed transaction. Production ingestion additionally needs malware/DLP controls, tenant isolation, durable job/audit state, provider retries, deletion reconciliation, embedding/version governance, and index verification.
