# ADR 0003: Weighted Hybrid Retrieval for the PoC

- Status: Accepted (design decision; implementation planned)
- Date: 2026-07-10

## Context

Organizational queries need semantic matching and precise keyword/identifier matching. Evidence must be authorized, attributable, and efficiently retrieved from Pinecone.

## Decision

Store dense and sparse representations in Pinecone and use a configurable weighted score combination for the PoC. Tune the weight against a versioned evaluation set, deduplicate by content hash, enforce diversity, and optionally rerank only authorized candidates later.

## Alternatives considered

- Dense only: simple but weaker for exact terms and identifiers.
- Sparse only: interpretable but weaker for semantic paraphrase.
- Reciprocal Rank Fusion: robust to score-scale mismatch but normally requires separate lists and discards magnitude.
- Mandatory cross-encoder reranking: potentially higher quality but adds latency, cost, and another model boundary.

## Consequences

One hybrid query is efficient and easy to tune, but calibration can vary by corpus/model. Evaluation must guard upgrades; RRF remains a documented production alternative.

## Security implications

Backend-derived namespace and role filters are mandatory before retrieval and are rechecked afterward. Missing access metadata fails closed. Untrusted retrieved content is validated before model context.
