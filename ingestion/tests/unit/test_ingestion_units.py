"""Unit tests for safe parsing, normalization, chunking, IDs, and metadata."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from enterprise_ai_ingestion.chunker import chunk_document
from enterprise_ai_ingestion.config import IngestionConfig
from enterprise_ai_ingestion.exceptions import (
    FrontMatterError,
    SourceHashMismatchError,
    UnsafeSourcePathError,
    UnsupportedMetadataError,
)
from enterprise_ai_ingestion.models import BlockKind, ParsedDocument
from enterprise_ai_ingestion.normalizer import normalize_body
from enterprise_ai_ingestion.parser import (
    load_manifest,
    parse_front_matter,
    parse_source,
)
from enterprise_ai_ingestion.tokenizer import RegexTokenEstimator


def _source_root(
    tmp_path: Path, body: str, **metadata_changes: object
) -> tuple[Path, dict[str, object]]:
    metadata: dict[str, object] = {
        "document_id": str(uuid4()),
        "title": "Synthetic Parser Fixture",
        "source": "test-fixture",
        "department": "payments",
        "document_type": "runbook",
        "access_level": "confidential",
        "allowed_roles": ["analyst", "administrator"],
        "created_date": "2026-01-01",
        "updated_date": "2026-01-02",
        "version": "1.0",
        "owner": "Test Owner",
        "status": "active",
        "tags": ["test"],
        "related_document_ids": [],
    }
    metadata.update(metadata_changes)
    relative = "data/sample_documents/runbooks/test.md"
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    front = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    source.write_text(f"---\n{front}\n---\n{body}", encoding="utf-8", newline="\n")
    entry = {
        **metadata,
        "file_path": relative,
        "content_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "approximate_word_count": len(body.split()),
        "payment_related": False,
        "root_cause_category": None,
    }
    manifest = tmp_path / "data/sample_documents/manifest.json"
    manifest.write_text(json.dumps([entry]), encoding="utf-8")
    return tmp_path, entry


def _parsed(
    tmp_path: Path, body: str, **metadata: object
) -> tuple[ParsedDocument, IngestionConfig]:
    root, _ = _source_root(tmp_path, body, **metadata)
    config = IngestionConfig(source_root=root, output_root=tmp_path / "processed")
    return parse_source(load_manifest(config)[0], config), config


def test_valid_front_matter_unicode_and_source_lines_parse(tmp_path: Path) -> None:
    body = "# Résilience\n\nUnicode café content.\n"
    parsed, _ = _parsed(tmp_path, body)
    assert "café" in parsed.normalized_body
    block = parsed.sections[0].blocks[-1]
    assert block.source_line_start > parsed.source.body_source_line_start
    assert block.source_line_end >= block.source_line_start


@pytest.mark.parametrize(
    "text",
    [
        "No front matter",
        "---\ntitle: one\ntitle: two\n---\nBody",
        "---\nvalue: !!python/object:builtins.object {}\n---\nBody",
    ],
)
def test_malformed_duplicate_or_unsafe_yaml_is_rejected(text: str) -> None:
    with pytest.raises(FrontMatterError):
        parse_front_matter(text, maximum_bytes=10_000)


def test_manifest_disagreement_and_body_hash_mismatch_are_rejected(tmp_path: Path) -> None:
    root, entry = _source_root(tmp_path, "# Heading\n\nBody\n")
    config = IngestionConfig(source_root=root, output_root=tmp_path / "processed")
    source = load_manifest(config)[0]
    source.path.write_text(source.path.read_text().replace("Test Owner", "Other Owner"))
    with pytest.raises(UnsupportedMetadataError):
        parse_source(source, config)
    source.path.write_text(source.path.read_text().replace("Other Owner", "Test Owner"))
    entry["content_hash"] = "0" * 64
    (root / "data/sample_documents/manifest.json").write_text(json.dumps([entry]))
    with pytest.raises(SourceHashMismatchError):
        parse_source(load_manifest(config)[0], config)


@pytest.mark.parametrize(
    "source_file",
    ["../outside.md", "C:/absolute.md", "data/security_fixtures/injection.md"],
)
def test_unsafe_manifest_paths_are_rejected(tmp_path: Path, source_file: str) -> None:
    manifest = tmp_path / "data/sample_documents/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps([{"document_id": str(uuid4()), "file_path": source_file}]))
    config = IngestionConfig(source_root=tmp_path, output_root=tmp_path / "processed")
    with pytest.raises(UnsafeSourcePathError):
        load_manifest(config)


def test_fenced_code_is_preserved_and_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    body = f"# Safe code\n\n```python\nopen({str(marker)!r}, 'w')\n```\n"
    parsed, _ = _parsed(tmp_path, body)
    assert any(
        block.kind is BlockKind.CODE_FENCE
        for section in parsed.sections
        for block in section.blocks
    )
    assert not marker.exists()


def test_normalization_is_idempotent_and_preserves_markdown() -> None:
    source = "#  Café\r\n\r\n- item  \r\n\r\n| A | B |\r\n|---|---|\r\n```\r\ncode  \r\n```\r\n"
    once, _ = normalize_body(source, source_line_start=1)
    twice, _ = normalize_body(once, source_line_start=1)
    assert once == twice
    assert "# Café" in once and "- item" in once and "| A | B |" in once
    assert "```" in once and "code" in once


def test_large_section_chunks_deterministically_with_overlap_and_maximum(tmp_path: Path) -> None:
    paragraphs = [f"Paragraph {index} has six stable lexical words." for index in range(20)]
    body = "# Large Section\n\n" + "\n\n".join(paragraphs) + "\n"
    parsed, config = _parsed(tmp_path, body)
    config = config.model_copy(
        update={
            "target_chunk_tokens": 8,
            "maximum_chunk_tokens": 45,
            "overlap_tokens": 10,
            "minimum_chunk_tokens": 5,
        }
    )
    tokenizer = RegexTokenEstimator()
    first = chunk_document(parsed, config, tokenizer)
    second = chunk_document(parsed, config, tokenizer)
    assert first == second
    assert len(first) > 1
    assert any(chunk.overlap_token_count > 0 for chunk in first)
    assert all(0 < chunk.approximate_token_count <= 45 for chunk in first)
    assert len({chunk.chunk_id for chunk in first}) == len(first)
    assert len({chunk.evidence_id for chunk in first}) == len(first)
    assert all(any(paragraph in chunk.text for chunk in first) for paragraph in paragraphs)


def test_compatible_paragraphs_lists_and_sibling_sections_merge(tmp_path: Path) -> None:
    body = (
        "# Guide\n\n## Preparation\n\nFirst compatible paragraph.\n\n"
        "Second compatible paragraph.\n\n- first action\n- second action\n\n"
        "## Validation\n\nConfirm the compatible result.\n"
    )
    parsed, config = _parsed(tmp_path, body)
    config = config.model_copy(
        update={
            "target_chunk_tokens": 100,
            "maximum_chunk_tokens": 120,
            "minimum_chunk_tokens": 20,
        }
    )
    chunks = chunk_document(parsed, config, RegexTokenEstimator())
    assert len(chunks) == 1
    assert "First compatible paragraph" in chunks[0].text
    assert "Second compatible paragraph" in chunks[0].text
    assert "- first action\n- second action" in chunks[0].text
    assert "## Preparation" in chunks[0].text and "## Validation" in chunks[0].text
    assert chunks[0].source_line_start < chunks[0].source_line_end


def test_incompatible_top_level_sections_do_not_merge(tmp_path: Path) -> None:
    words = " ".join(f"control{index}" for index in range(30))
    body = f"# First domain\n\n{words}\n\n# Second domain\n\n{words}\n"
    parsed, config = _parsed(tmp_path, body)
    config = config.model_copy(
        update={
            "target_chunk_tokens": 100,
            "maximum_chunk_tokens": 120,
            "minimum_chunk_tokens": 20,
        }
    )
    chunks = chunk_document(parsed, config, RegexTokenEstimator())
    assert len(chunks) == 2
    assert "# Second domain" not in chunks[0].text
    assert "# First domain" not in chunks[1].text


def test_complete_small_document_is_the_only_small_chunk_exception(tmp_path: Path) -> None:
    parsed, config = _parsed(tmp_path, "# Notice\n\nBrief authoritative clause.\n")
    chunks = chunk_document(parsed, config, RegexTokenEstimator())
    assert len(chunks) == 1
    assert chunks[0].approximate_token_count < config.minimum_chunk_tokens


def test_token_estimator_is_sensible_versioned_and_deterministic() -> None:
    estimator = RegexTokenEstimator()
    paragraph = " ".join(f"word{index}" for index in range(100))
    identifiers = "INC-PAY-2026-004 HorizonPay api_gateway latency_ms=250."
    unicode_text = (
        "Caf\u00e9 payments \u2014 \u0dc3\u0dd2\u0d82\u0dc4\u0dbd "
        "\u0db4\u0dd9\u0dc5 deterministically."
    )
    assert 100 <= estimator.count(paragraph) <= 110
    assert estimator.tokens(identifiers) == estimator.tokens(identifiers)
    assert estimator.count(identifiers) >= 6
    assert estimator.count(unicode_text) == estimator.count(unicode_text)
    assert estimator.name and estimator.version


def test_changed_text_changes_chunk_id_and_metadata_is_exact(tmp_path: Path) -> None:
    body = "# Controls\n\nConfidential control content is preserved.\n"
    document_id = str(uuid4())
    parsed, config = _parsed(tmp_path / "one", body, document_id=document_id)
    changed, changed_config = _parsed(
        tmp_path / "two", body.replace("preserved", "retained"), document_id=document_id
    )
    tokenizer = RegexTokenEstimator()
    original_chunks = chunk_document(parsed, config, tokenizer)
    changed_chunks = chunk_document(changed, changed_config, tokenizer)
    assert original_chunks[0].chunk_id != changed_chunks[0].chunk_id
    chunk = original_chunks[0]
    metadata = parsed.source.metadata
    assert chunk.access_level == metadata.access_level
    assert chunk.allowed_roles == metadata.allowed_roles
    assert chunk.department == metadata.department
    assert chunk.document_type == metadata.document_type
    assert chunk.status == metadata.status
    assert chunk.version == metadata.version
    assert chunk.owner == metadata.owner
