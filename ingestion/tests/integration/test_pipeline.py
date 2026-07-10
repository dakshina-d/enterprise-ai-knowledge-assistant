"""Integration tests for the complete deterministic offline pipeline."""

import asyncio
import json
import statistics
from pathlib import Path

import pytest
from enterprise_ai_ingestion.config import IngestionConfig, repository_root
from enterprise_ai_ingestion.exceptions import (
    ArtifactDriftError,
    ArtifactValidationError,
    SourceManifestError,
)
from enterprise_ai_ingestion.parser import load_manifest, parse_source
from enterprise_ai_ingestion.pipeline import IngestionPipeline


def _config(output: Path, *, concurrency: int = 8, maximum_documents: int = 500) -> IngestionConfig:
    return IngestionConfig(
        source_root=repository_root(),
        output_root=output,
        concurrency=concurrency,
        maximum_documents=maximum_documents,
    )


def test_all_corpus_documents_build_with_deterministic_order_and_metadata(tmp_path: Path) -> None:
    pipeline = IngestionPipeline(_config(tmp_path / "processed"))
    bundle = asyncio.run(pipeline.build())
    assert len(bundle.documents) == 51
    assert len(bundle.chunks) >= 51
    assert all(document.chunk_count >= 1 for document in bundle.documents)
    assert len({chunk.chunk_id for chunk in bundle.chunks}) == len(bundle.chunks)
    assert len({chunk.evidence_id for chunk in bundle.chunks}) == len(bundle.chunks)
    assert not any("security_fixtures" in item.source_file for item in bundle.documents)
    assert not any("GLOSSARY.md" in item.source_file for item in bundle.documents)
    assert all("\\" not in item.source_file for item in bundle.documents)
    assert set(bundle.files) == {
        "documents.jsonl",
        "chunks.jsonl",
        "ingestion_manifest.json",
    }


def test_repeated_concurrency_levels_produce_byte_identical_artifacts(tmp_path: Path) -> None:
    one = asyncio.run(IngestionPipeline(_config(tmp_path / "one", concurrency=1)).expected_bundle())
    many = asyncio.run(
        IngestionPipeline(_config(tmp_path / "many", concurrency=16)).expected_bundle()
    )
    assert one.files == many.files


def test_check_detects_drift_and_validate_detects_modified_chunk(tmp_path: Path) -> None:
    output = tmp_path / "processed"
    pipeline = IngestionPipeline(_config(output))
    asyncio.run(pipeline.build())
    assert asyncio.run(pipeline.check()).manifest.document_count == 51
    chunks = output / "chunks.jsonl"
    chunks.write_bytes(chunks.read_bytes() + b"{}\n")
    with pytest.raises(ArtifactDriftError):
        asyncio.run(pipeline.check())
    with pytest.raises(ArtifactValidationError):
        asyncio.run(pipeline.validate())


def test_failed_build_preserves_existing_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "processed"
    pipeline = IngestionPipeline(_config(output))
    asyncio.run(pipeline.build())
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    failing = IngestionPipeline(_config(output, maximum_documents=1))
    with pytest.raises(SourceManifestError):
        asyncio.run(failing.build())
    after = {path.name: path.read_bytes() for path in output.iterdir()}
    assert before == after


def test_transaction_preserves_unmanaged_files(tmp_path: Path) -> None:
    output = tmp_path / "processed"
    output.mkdir()
    marker = output / "README.keep"
    marker.write_text("unmanaged")
    asyncio.run(IngestionPipeline(_config(output)).build())
    assert marker.read_text() == "unmanaged"


def test_fingerprint_changes_with_chunk_configuration(tmp_path: Path) -> None:
    default = asyncio.run(IngestionPipeline(_config(tmp_path / "default")).expected_bundle())
    changed_config = _config(tmp_path / "changed").model_copy(update={"target_chunk_tokens": 300})
    changed = asyncio.run(IngestionPipeline(changed_config).expected_bundle())
    assert default.manifest.build_fingerprint != changed.manifest.build_fingerprint


def test_corpus_specific_authority_access_and_incident_metadata(tmp_path: Path) -> None:
    bundle = asyncio.run(IngestionPipeline(_config(tmp_path / "processed")).expected_bundle())
    assert set(bundle.manifest.count_by_document_type) == {
        "policy",
        "architecture",
        "runbook",
        "incident",
        "product_specification",
        "meeting_note",
    }
    assert set(bundle.manifest.count_by_access_level) == {
        "public",
        "internal",
        "confidential",
        "restricted",
    }
    statuses = {document.status for document in bundle.documents}
    assert {"superseded", "draft", "archived"} <= statuses
    incidents = [
        document for document in bundle.documents if document.document_type.value == "incident"
    ]
    assert len(incidents) >= 16
    source_manifest = json.loads(
        (repository_root() / "data/sample_documents/manifest.json").read_text()
    )
    assert sum(bool(item["payment_related"]) for item in source_manifest) >= 10
    restricted_ids = {
        document.document_id
        for document in bundle.documents
        if document.access_level.value == "restricted"
    }
    assert all(
        chunk.allowed_roles == (chunk.allowed_roles[0],)
        and chunk.allowed_roles[0].value == "administrator"
        for chunk in bundle.chunks
        if chunk.document_id in restricted_ids
    )


def test_corpus_chunk_distribution_completeness_and_citation_quality(tmp_path: Path) -> None:
    config = _config(tmp_path / "processed")
    bundle = asyncio.run(IngestionPipeline(config).expected_bundle())
    counts = [chunk.approximate_token_count for chunk in bundle.chunks]
    assert statistics.median(counts) >= 250
    assert sum(count < config.minimum_chunk_tokens for count in counts) / len(counts) <= 0.05
    assert max(counts) <= config.maximum_chunk_tokens
    assert all(chunk.text.strip() for chunk in bundle.chunks)
    assert all(
        not all(line.lstrip().startswith("#") for line in chunk.text.splitlines() if line.strip())
        for chunk in bundle.chunks
    )
    parsed = tuple(parse_source(source, config) for source in load_manifest(config))
    chunks_by_id = {
        document.source.metadata.document_id: [
            chunk
            for chunk in bundle.chunks
            if chunk.document_id == document.source.metadata.document_id
        ]
        for document in parsed
    }
    for document in parsed:
        chunks = chunks_by_id[document.source.metadata.document_id]
        assert len({chunk.text for chunk in chunks}) == len(chunks)
        assert all(
            any(block.text in chunk.text for chunk in chunks)
            for section in document.sections
            for block in section.blocks
        )
        assert all(
            document.source.body_source_line_start
            <= chunk.source_line_start
            <= chunk.source_line_end
            for chunk in chunks
        )
        assert all(chunk.search_text.endswith(chunk.text) for chunk in chunks)
        assert all(len(chunk.search_text) - len(chunk.text) < len(chunk.text) for chunk in chunks)
