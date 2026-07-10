"""Deterministic BM25 artifact build, validation, drift check, and writes."""

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from uuid import uuid4

from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.exceptions import RetrievalDataIntegrityError
from enterprise_ai.retrieval.indexer import load_current_chunks
from enterprise_ai.retrieval.sparse.analyzer import (
    ANALYZER_NAME,
    ANALYZER_VERSION,
    STOP_WORD_VERSION,
    analyze,
)

SPARSE_SCHEMA_VERSION = "1.0"
BM25_ALGORITHM_VERSION = "okapi-bm25-1.0"


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def expected_artifacts(settings: RetrievalSettings) -> tuple[dict[str, object], dict[str, bytes]]:
    manifest, chunks = load_current_chunks(settings)
    if len(chunks) > settings.bm25_max_indexed_chunks:
        raise RetrievalDataIntegrityError("sparse corpus exceeds configured chunk limit")
    documents: dict[str, dict[str, object]] = {}
    document_frequencies: Counter[str] = Counter()
    total_length = 0
    for chunk in chunks:
        terms = analyze(chunk.search_text)
        if not terms or len(terms) > settings.bm25_max_terms_per_chunk:
            raise RetrievalDataIntegrityError("sparse chunk term count is invalid")
        frequencies = Counter(terms)
        document_frequencies.update(frequencies.keys())
        total_length += len(terms)
        documents[str(chunk.chunk_id)] = {
            "length": len(terms),
            "term_frequencies": dict(sorted(frequencies.items())),
        }
    if len(document_frequencies) > settings.bm25_max_vocabulary_size:
        raise RetrievalDataIntegrityError("sparse vocabulary exceeds configured limit")
    source_hash = next(
        item.sha256 for item in manifest.artifacts if item.filename == "chunks.jsonl"
    )
    fingerprint_input = {
        "ingestion_build_fingerprint": manifest.build_fingerprint,
        "chunk_artifact_hash": source_hash,
        "analyzer": [ANALYZER_NAME, ANALYZER_VERSION, STOP_WORD_VERSION],
        "algorithm": BM25_ALGORITHM_VERSION,
        "k1": settings.bm25_k1,
        "b": settings.bm25_b,
        "schema": SPARSE_SCHEMA_VERSION,
    }
    fingerprint = hashlib.sha256(canonical(fingerprint_input)).hexdigest()
    index = {
        "schema_version": SPARSE_SCHEMA_VERSION,
        "documents": documents,
        "document_frequencies": dict(sorted(document_frequencies.items())),
    }
    index_bytes = canonical(index)
    sparse_manifest = {
        "schema_version": SPARSE_SCHEMA_VERSION,
        "analyzer_name": ANALYZER_NAME,
        "analyzer_version": ANALYZER_VERSION,
        "stop_word_version": STOP_WORD_VERSION,
        "bm25_algorithm_version": BM25_ALGORITHM_VERSION,
        "k1": settings.bm25_k1,
        "b": settings.bm25_b,
        "ingestion_build_fingerprint": manifest.build_fingerprint,
        "chunk_artifact_hash": source_hash,
        "indexed_chunk_count": len(chunks),
        "average_document_length": total_length / len(chunks),
        "vocabulary_size": len(document_frequencies),
        "sparse_build_fingerprint": fingerprint,
        "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
    }
    files = {"bm25_index.json": index_bytes, "bm25_manifest.json": canonical(sparse_manifest)}
    return sparse_manifest, files


def build_sparse(settings: RetrievalSettings) -> dict[str, object]:
    manifest, files = expected_artifacts(settings)
    targets = (settings.bm25_index_path, settings.bm25_manifest_path)
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
    previous = {path: path.read_bytes() if path.is_file() else None for path in targets}
    staged: list[tuple[Path, Path]] = []
    try:
        for target, name in (
            (settings.bm25_index_path, "bm25_index.json"),
            (settings.bm25_manifest_path, "bm25_manifest.json"),
        ):
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            temporary.write_bytes(files[name])
            staged.append((temporary, target))
        for temporary, target in staged:
            os.replace(temporary, target)
    except Exception:
        for target, content in previous.items():
            if content is None:
                target.unlink(missing_ok=True)
            else:
                rollback = target.with_name(f".{target.name}.{uuid4().hex}.rollback")
                rollback.write_bytes(content)
                os.replace(rollback, target)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    validate_sparse(settings)
    return manifest


def check_sparse(settings: RetrievalSettings) -> dict[str, object]:
    manifest, files = expected_artifacts(settings)
    actual = {
        "bm25_index.json": settings.bm25_index_path.read_bytes(),
        "bm25_manifest.json": settings.bm25_manifest_path.read_bytes(),
    }
    if actual != files:
        raise RetrievalDataIntegrityError("sparse artifacts have drifted")
    return manifest


def validate_sparse(settings: RetrievalSettings) -> dict[str, object]:
    try:
        manifest = json.loads(settings.bm25_manifest_path.read_text(encoding="utf-8"))
        index = json.loads(settings.bm25_index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RetrievalDataIntegrityError("sparse artifacts are missing or malformed") from error
    expected_manifest, expected_files = expected_artifacts(settings)
    if (
        manifest != expected_manifest
        or settings.bm25_index_path.read_bytes() != expected_files["bm25_index.json"]
    ):
        raise RetrievalDataIntegrityError("sparse artifacts are stale or invalid")
    if (
        hashlib.sha256(settings.bm25_index_path.read_bytes()).hexdigest()
        != manifest["index_sha256"]
    ):
        raise RetrievalDataIntegrityError("sparse index hash is invalid")
    if not index["documents"]:
        raise RetrievalDataIntegrityError("sparse index contains no documents")
    return expected_manifest
