"""Validated deterministic ingestion configuration and repository defaults."""

from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

PIPELINE_VERSION = "1.1"
DOCUMENT_SCHEMA_VERSION = "1.0"
CHUNK_SCHEMA_VERSION = "1.1"


class IngestionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_root: Path
    output_root: Path
    target_chunk_tokens: int = Field(default=450, ge=1, le=10_000)
    maximum_chunk_tokens: int = Field(default=650, ge=1, le=10_000)
    overlap_tokens: int = Field(default=75, ge=0, le=2_000)
    minimum_chunk_tokens: int = Field(default=80, ge=1, le=2_000)
    concurrency: int = Field(default=8, ge=1, le=64)
    maximum_source_file_bytes: int = Field(default=1_000_000, ge=1)
    maximum_documents: int = Field(default=500, ge=1)
    maximum_front_matter_bytes: int = Field(default=64_000, ge=1)
    maximum_chunks_per_document: int = Field(default=500, ge=1)
    maximum_chunk_text_bytes: int = Field(default=256_000, ge=1)

    @model_validator(mode="after")
    def validate_chunking(self) -> Self:
        if self.target_chunk_tokens > self.maximum_chunk_tokens:
            raise ValueError("target chunk tokens cannot exceed maximum chunk tokens")
        if self.minimum_chunk_tokens > self.target_chunk_tokens:
            raise ValueError("minimum chunk tokens cannot exceed target chunk tokens")
        if self.overlap_tokens >= self.maximum_chunk_tokens:
            raise ValueError("overlap tokens must be smaller than maximum chunk tokens")
        return self


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_config() -> IngestionConfig:
    root = repository_root()
    return IngestionConfig(source_root=root, output_root=root / "data" / "processed")
