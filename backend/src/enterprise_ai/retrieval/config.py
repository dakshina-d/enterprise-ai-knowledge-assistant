"""Validated environment configuration for optional Pinecone retrieval."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from enterprise_ai.retrieval.exceptions import RetrievalConfigurationError


class RetrievalSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    pinecone_enabled: bool = False
    pinecone_api_key: SecretStr | None = None
    pinecone_index_name: str = Field(default="lhcb-knowledge-dev", pattern=r"^[a-z0-9-]{1,45}$")
    pinecone_index_host: str | None = None
    pinecone_namespace: str = Field(
        default="lhcb-knowledge-dev-v1", pattern=r"^[a-zA-Z0-9_-]{1,64}$"
    )
    pinecone_cloud: Literal["aws", "gcp", "azure"] = "aws"
    pinecone_region: str = Field(default="us-east-1", min_length=1, max_length=100)
    pinecone_metric: Literal["cosine", "dotproduct", "euclidean"] = "cosine"
    pinecone_dense_model: str = Field(default="llama-text-embed-v2", min_length=1, max_length=200)
    pinecone_dense_dimension: int = Field(default=1024, ge=1, le=20_000)
    pinecone_embed_batch_size: int = Field(default=32, ge=1, le=96)
    pinecone_upsert_batch_size: int = Field(default=50, ge=1, le=1000)
    pinecone_query_top_k: int = Field(default=10, ge=1, le=100)
    pinecone_request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    pinecone_max_retries: int = Field(default=3, ge=0, le=10)
    pinecone_retry_base_seconds: float = Field(default=0.25, gt=0, le=30)
    pinecone_max_embedding_input_chars: int = Field(default=16_000, ge=1, le=100_000)
    pinecone_max_metadata_bytes: int = Field(default=35_000, ge=1, le=40_000)
    pinecone_index_ready_timeout_seconds: float = Field(default=180.0, gt=0, le=1800)
    ingestion_manifest_path: Path = Path("data/processed/ingestion_manifest.json")
    ingestion_chunks_path: Path = Path("data/processed/chunks.jsonl")
    bm25_k1: float = Field(default=1.5, gt=0, le=10)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    bm25_max_query_tokens: int = Field(default=128, ge=1, le=1000)
    bm25_max_vocabulary_size: int = Field(default=100_000, ge=1)
    bm25_max_indexed_chunks: int = Field(default=10_000, ge=1)
    bm25_max_terms_per_chunk: int = Field(default=10_000, ge=1)
    bm25_index_path: Path = Path("data/processed/bm25_index.json")
    bm25_manifest_path: Path = Path("data/processed/bm25_manifest.json")
    hybrid_dense_weight: float = Field(default=0.65, ge=0, le=1)
    hybrid_sparse_weight: float = Field(default=0.35, ge=0, le=1)
    hybrid_overfetch_factor: int = Field(default=4, ge=1, le=20)
    hybrid_max_candidates: int = Field(default=100, ge=1, le=500)
    hybrid_dense_timeout_seconds: float = Field(default=30, gt=0, le=300)
    hybrid_sparse_timeout_seconds: float = Field(default=5, gt=0, le=60)
    hybrid_allow_partial_results: bool = True
    graph_max_steps: int = Field(default=20, ge=1, le=100)
    graph_max_recursion_depth: int = Field(default=2, ge=0, le=3)
    graph_timeout_seconds: float = Field(default=30, gt=0, le=300)
    graph_max_messages: int = Field(default=20, ge=1, le=100)
    graph_max_message_characters: int = Field(default=20_000, ge=1, le=100_000)
    graph_max_evidence_items: int = Field(default=20, ge=1, le=100)
    graph_max_warnings: int = Field(default=20, ge=1, le=100)
    graph_max_errors: int = Field(default=10, ge=1, le=100)
    graph_checkpoint_mode: Literal["memory"] = "memory"
    graph_offline_retrieval_mode: Literal["sparse", "hybrid"] = "sparse"
    memory_enabled: bool = True
    memory_max_sessions: int = Field(default=1_000, ge=1, le=100_000)
    memory_max_turns_per_session: int = Field(default=12, ge=1, le=100)
    memory_max_total_characters: int = Field(default=20_000, ge=1, le=1_000_000)
    memory_max_user_message_characters: int = Field(default=4_000, ge=1, le=4_000)
    memory_max_assistant_message_characters: int = Field(default=8_000, ge=1, le=32_000)
    memory_max_evidence_references: int = Field(default=50, ge=1, le=1_000)
    memory_session_ttl_seconds: int = Field(default=7_200, ge=1, le=604_800)
    memory_max_context_topics: int = Field(default=20, ge=1, le=100)
    memory_max_context_identifiers: int = Field(default=30, ge=1, le=200)
    memory_followup_context_enabled: bool = True
    memory_redact_sensitive_patterns: bool = True

    @model_validator(mode="after")
    def validate_enabled(self) -> Self:
        if self.hybrid_dense_weight + self.hybrid_sparse_weight <= 0:
            raise ValueError("at least one hybrid weight must be positive")
        if self.pinecone_enabled and (
            self.pinecone_api_key is None or not self.pinecone_api_key.get_secret_value()
        ):
            raise ValueError("PINECONE_API_KEY is required when Pinecone is enabled")
        return self

    def require_enabled(self) -> None:
        if not self.pinecone_enabled:
            raise RetrievalConfigurationError("Pinecone retrieval is disabled")
        if self.pinecone_api_key is None:
            raise RetrievalConfigurationError("Pinecone configuration is incomplete")

    def api_key_value(self) -> str:
        self.require_enabled()
        if self.pinecone_api_key is None:
            raise RetrievalConfigurationError("Pinecone configuration is incomplete")
        return self.pinecone_api_key.get_secret_value()
