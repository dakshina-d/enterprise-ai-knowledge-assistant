"""Safe manifest-authoritative Markdown and YAML front-matter parsing."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from enterprise_ai_ingestion.config import IngestionConfig
from enterprise_ai_ingestion.exceptions import (
    FrontMatterError,
    MarkdownParseError,
    SourceFileMissingError,
    SourceHashMismatchError,
    SourceManifestError,
    UnsafeSourcePathError,
    UnsupportedMetadataError,
)
from enterprise_ai_ingestion.models import (
    BlockKind,
    ManifestSource,
    MarkdownBlock,
    MarkdownSection,
    ParsedDocument,
    SourceDocument,
    SourceDocumentMetadata,
)
from enterprise_ai_ingestion.normalizer import NormalizedLine, normalize_body

VALID_STATUSES = {
    "approved",
    "active",
    "draft",
    "superseded",
    "archived",
    "final",
    "post_incident_final",
}
HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
LIST_ITEM = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")


class UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant rejecting duplicate mappings."""


def _construct_unique_mapping(
    loader: UniqueKeySafeLoader, node: MappingNode, deep: bool = False
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "duplicate front-matter key",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_manifest(config: IngestionConfig) -> tuple[ManifestSource, ...]:
    manifest_path = config.source_root / "data" / "sample_documents" / "manifest.json"
    try:
        raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SourceManifestError("source manifest is missing or invalid") from error
    if not isinstance(raw, list) or len(raw) > config.maximum_documents:
        raise SourceManifestError("source manifest document count is invalid")
    ids: set[str] = set()
    paths: set[str] = set()
    sources: list[ManifestSource] = []
    root = config.source_root.resolve()
    for value in raw:
        if not isinstance(value, dict):
            raise SourceManifestError("source manifest entry is invalid")
        entry = {str(key): item for key, item in value.items()}
        document_id = str(entry.get("document_id", ""))
        source_file = str(entry.get("file_path", ""))
        if document_id in ids or source_file in paths:
            raise SourceManifestError("source manifest contains duplicate identity")
        ids.add(document_id)
        paths.add(source_file)
        path = _safe_source_path(root, source_file)
        sources.append(ManifestSource(entry=entry, path=path, source_file=source_file))
    return tuple(sorted(sources, key=lambda item: item.source_file))


def _safe_source_path(root: Path, source_file: str) -> Path:
    relative = Path(source_file)
    posix_relative = PurePosixPath(source_file)
    windows_relative = PureWindowsPath(source_file)
    if (
        relative.is_absolute()
        or posix_relative.is_absolute()
        or windows_relative.is_absolute()
        or bool(windows_relative.drive)
        or ".." in relative.parts
        or ".." in windows_relative.parts
        or "\\" in source_file
    ):
        raise UnsafeSourcePathError("source manifest contains an unsafe path")
    if source_file.startswith("data/security_fixtures/") or source_file.endswith("GLOSSARY.md"):
        raise UnsafeSourcePathError("source manifest contains an excluded path")
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise SourceFileMissingError("source file is missing") from error
    if not resolved.is_relative_to(root) or candidate.is_symlink():
        raise UnsafeSourcePathError("source path escapes root or is a symlink")
    current = candidate.parent
    while current != root:
        if current.is_symlink():
            raise UnsafeSourcePathError("source path contains a symlink")
        current = current.parent
    return resolved


def parse_source(source: ManifestSource, config: IngestionConfig) -> ParsedDocument:
    if source.path.stat().st_size > config.maximum_source_file_bytes:
        raise SourceManifestError("source file exceeds configured size")
    try:
        text = source.path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise MarkdownParseError("source file cannot be read as UTF-8") from error
    metadata_raw, body, body_line_start = parse_front_matter(
        text, maximum_bytes=config.maximum_front_matter_bytes
    )
    metadata = _metadata(metadata_raw)
    manifest_metadata = _metadata(source.entry)
    if metadata != manifest_metadata:
        raise UnsupportedMetadataError("front matter disagrees with canonical manifest")
    original_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if source.entry.get("content_hash") != original_hash:
        raise SourceHashMismatchError("source body hash disagrees with canonical manifest")
    normalized, lines = normalize_body(body, source_line_start=body_line_start)
    sections = _sections(lines)
    return ParsedDocument(
        source=SourceDocument(
            metadata=metadata,
            source_file=source.source_file,
            original_body=body,
            original_content_hash=original_hash,
            body_source_line_start=body_line_start,
        ),
        normalized_body=normalized,
        normalized_content_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        sections=sections,
        heading_paths=tuple(section.heading_path for section in sections if section.heading_path),
    )


def parse_front_matter(text: str, *, maximum_bytes: int) -> tuple[dict[str, object], str, int]:
    canonical = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = canonical.split("\n")
    if not lines or lines[0] != "---":
        raise FrontMatterError("source is missing YAML front matter")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise FrontMatterError("source front matter is not terminated") from error
    encoded = "\n".join(lines[1:closing]).encode("utf-8")
    if len(encoded) > maximum_bytes:
        raise FrontMatterError("source front matter exceeds configured size")
    loader = UniqueKeySafeLoader(encoded.decode("utf-8"))
    try:
        loaded = loader.get_single_data()
    except yaml.YAMLError as error:
        raise FrontMatterError("source front matter is invalid") from error
    finally:
        loader.dispose()  # type: ignore[no-untyped-call]  # PyYAML stub omits annotation
    if not isinstance(loaded, dict) or any(not isinstance(key, str) for key in loaded):
        raise FrontMatterError("source front matter must be a string-key mapping")
    body_index = closing + 1
    while body_index < len(lines) and not lines[body_index]:
        body_index += 1
    body = "\n".join(lines[body_index:])
    if canonical.endswith("\n") and not body.endswith("\n"):
        body += "\n"
    if not body.strip():
        raise MarkdownParseError("source body is empty")
    return {str(key): value for key, value in loaded.items()}, body, body_index + 1


def _metadata(value: dict[str, Any] | dict[str, object]) -> SourceDocumentMetadata:
    fields = {
        "document_id",
        "title",
        "source",
        "department",
        "document_type",
        "access_level",
        "allowed_roles",
        "created_date",
        "updated_date",
        "version",
        "owner",
        "status",
        "tags",
        "related_document_ids",
    }
    try:
        metadata = SourceDocumentMetadata.model_validate({field: value[field] for field in fields})
    except (KeyError, ValueError, TypeError) as error:
        raise UnsupportedMetadataError("source metadata is missing or unsupported") from error
    if metadata.status not in VALID_STATUSES:
        raise UnsupportedMetadataError("source status is unsupported")
    return metadata


def _sections(lines: tuple[NormalizedLine, ...]) -> tuple[MarkdownSection, ...]:
    sections: list[MarkdownSection] = []
    current_lines: list[NormalizedLine] = []
    current_heading = "Document"
    current_level = 0
    path: list[str] = []

    def finish() -> None:
        if not current_lines:
            return
        blocks = _blocks(current_lines, tuple(path))
        if blocks:
            sections.append(
                MarkdownSection(
                    heading=current_heading,
                    heading_path=tuple(path),
                    level=current_level,
                    source_line_start=blocks[0].source_line_start,
                    source_line_end=blocks[-1].source_line_end,
                    blocks=blocks,
                )
            )

    for line in lines:
        heading = HEADING.match(line.text)
        if heading:
            finish()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            path[:] = path[: level - 1]
            path.append(title)
            current_heading = title
            current_level = level
            current_lines = [line]
        else:
            current_lines.append(line)
    finish()
    if not sections:
        raise MarkdownParseError("source produced no Markdown sections")
    return tuple(sections)


def _blocks(lines: list[NormalizedLine], path: tuple[str, ...]) -> tuple[MarkdownBlock, ...]:
    blocks: list[MarkdownBlock] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.text:
            index += 1
            continue
        kind = _kind(line.text)
        group = [line]
        index += 1
        if kind == BlockKind.CODE_FENCE:
            while index < len(lines):
                group.append(lines[index])
                index += 1
                if group[-1].text.strip().startswith("```") and len(group) > 1:
                    break
        elif kind != BlockKind.HEADING:
            while index < len(lines) and lines[index].text:
                if _kind(lines[index].text) != kind:
                    break
                group.append(lines[index])
                index += 1
        text = "\n".join(item.text for item in group).strip()
        if text:
            blocks.append(
                MarkdownBlock(
                    kind=kind,
                    text=text,
                    source_line_start=group[0].source_line,
                    source_line_end=group[-1].source_line,
                    section_path=path,
                )
            )
    return tuple(blocks)


def _kind(text: str) -> BlockKind:
    if HEADING.match(text):
        return BlockKind.HEADING
    stripped = text.lstrip()
    if stripped.startswith("```"):
        return BlockKind.CODE_FENCE
    if stripped.startswith("|"):
        return BlockKind.TABLE
    if stripped.startswith(">"):
        return BlockKind.BLOCKQUOTE
    if LIST_ITEM.match(text):
        return BlockKind.LIST
    return BlockKind.PARAGRAPH
