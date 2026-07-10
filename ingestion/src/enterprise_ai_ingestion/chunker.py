"""Deterministic section/block-aware chunk construction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from enterprise_ai_ingestion.config import CHUNK_SCHEMA_VERSION, IngestionConfig
from enterprise_ai_ingestion.exceptions import ChunkingError
from enterprise_ai_ingestion.models import (
    BlockKind,
    ChunkRecord,
    MarkdownBlock,
    ParsedDocument,
)
from enterprise_ai_ingestion.tokenizer import TokenEstimator

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    blocks: tuple[MarkdownBlock, ...]
    overlap_token_count: int


def chunk_document(
    document: ParsedDocument, config: IngestionConfig, tokenizer: TokenEstimator
) -> tuple[ChunkRecord, ...]:
    expanded = tuple(
        part
        for section in document.sections
        for block in section.blocks
        for part in _split_oversized_block(block, config.maximum_chunk_tokens, tokenizer)
    )
    drafts = list(_pack_document(expanded, config, tokenizer))
    if not drafts or len(drafts) > config.maximum_chunks_per_document:
        raise ChunkingError("document produced an invalid number of chunks")
    records = tuple(
        _record(document, draft, index, tokenizer) for index, draft in enumerate(drafts)
    )
    if any(record.approximate_token_count > config.maximum_chunk_tokens for record in records):
        raise ChunkingError("generated chunk exceeds configured token maximum")
    if any(
        len(record.text.encode("utf-8")) > config.maximum_chunk_text_bytes for record in records
    ):
        raise ChunkingError("generated chunk exceeds configured byte maximum")
    _validate_coverage(document, records)
    _validate_chunk_quality(records, config)
    return records


def _pack_document(
    blocks: tuple[MarkdownBlock, ...],
    config: IngestionConfig,
    tokenizer: TokenEstimator,
) -> tuple[ChunkDraft, ...]:
    if not blocks:
        return ()
    cores: list[tuple[MarkdownBlock, ...]] = []
    current: list[MarkdownBlock] = []
    current_count = 0
    for block in blocks:
        count = tokenizer.count(block.text)
        separator = 1 if current else 0
        incompatible_boundary = current and not _paths_compatible(
            current[-1].section_path, block.section_path
        )
        if current and (
            incompatible_boundary
            or (
                current_count + separator + count > config.target_chunk_tokens
                and not all(item.kind is BlockKind.HEADING for item in current)
            )
        ):
            cores.append(tuple(current))
            current = []
            current_count = 0
        current.append(block)
        current_count += separator + count
        if current_count >= config.target_chunk_tokens:
            cores.append(tuple(current))
            current = []
            current_count = 0
    if current:
        if cores and tokenizer.count(_text(tuple(current))) < config.minimum_chunk_tokens:
            candidate = (*cores[-1], *current)
            if tokenizer.count(_text(candidate)) <= config.maximum_chunk_tokens:
                cores[-1] = candidate
            else:
                cores.append(tuple(current))
        else:
            cores.append(tuple(current))
    _rebalance_final_core(cores, config, tokenizer)

    drafts: list[ChunkDraft] = []
    previous_core: tuple[MarkdownBlock, ...] = ()
    for core in cores:
        overlap: list[MarkdownBlock] = []
        overlap_count = 0
        if tokenizer.count(_text(core)) >= config.target_chunk_tokens:
            for block in reversed(previous_core):
                if block.section_path != core[0].section_path:
                    break
                block_count = tokenizer.count(block.text)
                if overlap_count + block_count > config.overlap_tokens:
                    break
                overlap.insert(0, block)
                overlap_count += block_count
        while overlap and tokenizer.count(_text((*overlap, *core))) > config.maximum_chunk_tokens:
            removed = overlap.pop(0)
            overlap_count -= tokenizer.count(removed.text)
        drafts.append(ChunkDraft((*overlap, *core), max(0, overlap_count)))
        previous_core = core
    return tuple(drafts)


def _paths_compatible(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if not left or not right:
        return True
    return left[0] == right[0]


def _rebalance_final_core(
    cores: list[tuple[MarkdownBlock, ...]],
    config: IngestionConfig,
    tokenizer: TokenEstimator,
) -> None:
    if len(cores) < 2:
        return
    preferred_floor = max(config.minimum_chunk_tokens, config.target_chunk_tokens // 2)
    while tokenizer.count(_text(cores[-1])) < preferred_floor:
        previous = list(cores[-2])
        trailing_path = previous[-1].section_path
        split_at = len(previous) - 1
        while split_at and previous[split_at - 1].section_path == trailing_path:
            split_at -= 1
        if split_at == 0:
            break
        retained = tuple(previous[:split_at])
        moved = tuple(previous[split_at:])
        if not _paths_compatible(moved[-1].section_path, cores[-1][0].section_path):
            break
        candidate = (*moved, *cores[-1])
        if (
            tokenizer.count(_text(retained)) < preferred_floor
            or tokenizer.count(_text(candidate)) > config.maximum_chunk_tokens
        ):
            break
        cores[-2] = retained
        cores[-1] = candidate


def _split_oversized_block(
    block: MarkdownBlock, maximum: int, tokenizer: TokenEstimator
) -> tuple[MarkdownBlock, ...]:
    if tokenizer.count(block.text) <= maximum:
        return (block,)
    line_parts = block.text.splitlines()
    if len(line_parts) > 1 and block.kind not in {BlockKind.TABLE, BlockKind.CODE_FENCE}:
        parts: list[MarkdownBlock] = []
        for offset, line in enumerate(line_parts):
            parts.extend(
                _split_text(
                    line,
                    block,
                    maximum,
                    tokenizer,
                    min(block.source_line_start + offset, block.source_line_end),
                )
            )
        return tuple(parts)
    return _split_text(block.text, block, maximum, tokenizer, block.source_line_start)


def _split_text(
    text: str,
    block: MarkdownBlock,
    maximum: int,
    tokenizer: TokenEstimator,
    source_line: int,
) -> tuple[MarkdownBlock, ...]:
    sentences = SENTENCE_END.split(text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and tokenizer.count(candidate) > maximum:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    final: list[str] = []
    for piece in pieces:
        if tokenizer.count(piece) <= maximum:
            final.append(piece)
            continue
        matches = list(re.finditer(r"\S+", piece))
        for start in range(0, len(matches), maximum):
            group = matches[start : start + maximum]
            final.append(piece[group[0].start() : group[-1].end()])
    return tuple(
        MarkdownBlock(
            kind=block.kind,
            text=piece,
            source_line_start=source_line,
            source_line_end=max(source_line, block.source_line_end),
            section_path=block.section_path,
        )
        for piece in final
        if piece.strip()
    )


def _record(
    document: ParsedDocument,
    draft: ChunkDraft,
    index: int,
    tokenizer: TokenEstimator,
) -> ChunkRecord:
    metadata = document.source.metadata
    text = _text(draft.blocks)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    section_path = _common_section_path(draft.blocks)
    path_key = "/".join(section_path)
    chunk_id = uuid5(
        NAMESPACE_URL,
        f"lhcb-chunk:{CHUNK_SCHEMA_VERSION}:{tokenizer.name}:{tokenizer.version}:"
        f"{metadata.document_id}:{path_key}:{index}:{content_hash}",
    )
    evidence_id = uuid5(
        NAMESPACE_URL,
        f"lhcb-evidence:{metadata.document_id}:{chunk_id}:{metadata.version}",
    )
    heading = section_path[-1] if section_path else "Document"
    search_context = (
        f"Title: {metadata.title}\nDocument type: {metadata.document_type.value}\n"
        f"Department: {metadata.department}\nSection: {' > '.join(section_path)}"
    )
    return ChunkRecord(
        schema_version=CHUNK_SCHEMA_VERSION,
        chunk_id=chunk_id,
        document_id=metadata.document_id,
        chunk_index=index,
        evidence_id=evidence_id,
        title=metadata.title,
        source=metadata.source,
        source_file=document.source.source_file,
        department=metadata.department,
        document_type=metadata.document_type,
        access_level=metadata.access_level,
        allowed_roles=metadata.allowed_roles,
        created_date=metadata.created_date,
        updated_date=metadata.updated_date,
        version=metadata.version,
        owner=metadata.owner,
        status=metadata.status,
        tags=metadata.tags,
        related_document_ids=metadata.related_document_ids,
        section=heading,
        section_path=section_path,
        source_line_start=min(block.source_line_start for block in draft.blocks),
        source_line_end=max(block.source_line_end for block in draft.blocks),
        text=text,
        search_text=f"{search_context}\n\n{text}",
        approximate_token_count=tokenizer.count(text),
        overlap_token_count=draft.overlap_token_count,
        chunk_content_hash=content_hash,
        original_document_hash=document.source.original_content_hash,
        normalized_document_hash=document.normalized_content_hash,
    )


def _text(blocks: tuple[MarkdownBlock, ...]) -> str:
    return "\n\n".join(block.text for block in blocks).strip()


def _common_section_path(blocks: tuple[MarkdownBlock, ...]) -> tuple[str, ...]:
    common = list(blocks[0].section_path)
    for block in blocks[1:]:
        common = [
            value
            for index, value in enumerate(common)
            if index < len(block.section_path) and block.section_path[index] == value
        ]
    return tuple(common)


def _validate_coverage(document: ParsedDocument, records: tuple[ChunkRecord, ...]) -> None:
    combined = "\n".join(record.text for record in records)
    for section in document.sections:
        for block in section.blocks:
            if not any(block.text in record.text for record in records) and not all(
                token in combined for token in block.text.split()
            ):
                raise ChunkingError("normalized source block was not preserved in chunks")


def _validate_chunk_quality(
    records: tuple[ChunkRecord, ...],
    config: IngestionConfig,
) -> None:
    primary_texts: set[str] = set()
    for record in records:
        if not record.text.strip():
            raise ChunkingError("generated chunk is empty")
        nonblank_lines = [line for line in record.text.splitlines() if line.strip()]
        if nonblank_lines and all(line.lstrip().startswith("#") for line in nonblank_lines):
            raise ChunkingError("generated chunk contains headings only")
        if record.text in primary_texts:
            raise ChunkingError("document contains duplicate chunk text")
        primary_texts.add(record.text)
        if record.approximate_token_count < config.minimum_chunk_tokens and len(records) > 1:
            raise ChunkingError("avoidable undersized chunk was generated")
