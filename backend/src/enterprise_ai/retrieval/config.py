"""Validated environment configuration for optional Pinecone retrieval."""

from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
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
    app_env: Literal["development", "test", "staging", "production"] = "development"
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = Field(
        default="enterprise-ai-knowledge-assistant-dev", min_length=1, max_length=200
    )
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com", min_length=1, max_length=500
    )
    langsmith_workspace_id: str | None = Field(default=None, max_length=200)
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
    python_analysis_enabled: bool = True
    python_analysis_max_rows: int = Field(default=1_000, ge=1, le=10_000)
    python_analysis_max_groups: int = Field(default=100, ge=1, le=1_000)
    python_analysis_max_result_items: int = Field(default=50, ge=1, le=500)
    python_analysis_max_filter_values: int = Field(default=50, ge=1, le=500)
    python_analysis_timeout_seconds: float = Field(default=5, gt=0, le=60)
    python_analysis_max_text_field_characters: int = Field(default=2_000, ge=1, le=10_000)
    python_analysis_max_distinct_values: int = Field(default=500, ge=1, le=5_000)
    python_analysis_allow_partial_rows: bool = True
    llm_enabled: bool = True
    llm_provider: Literal["fake", "ollama", "openai"] = "fake"
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", max_length=300)
    ollama_allow_remote: bool = False
    ollama_model: str = Field(
        default="qwen3:4b-instruct",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    )
    ollama_request_timeout_seconds: float = Field(default=120, ge=1, le=300)
    ollama_num_ctx: int = Field(default=8_192, ge=512, le=65_536)
    ollama_num_predict: int = Field(default=800, ge=64, le=4_096)
    ollama_temperature: Literal[0] = 0
    ollama_keep_alive: str = Field(default="5m", pattern=r"^[1-9][0-9]{0,2}[smh]$")
    openai_api_key: SecretStr | None = None
    openai_response_model: str = "gpt-5.4-mini"
    openai_response_timeout_seconds: float = Field(default=30, gt=0, le=300)
    openai_response_max_retries: int = Field(default=2, ge=0, le=5)
    openai_response_retry_base_seconds: float = Field(default=0.25, gt=0, le=10)
    openai_response_max_output_tokens: int = Field(default=1_500, ge=64, le=16_000)
    openai_response_temperature: float = Field(default=0.1, ge=0, le=1)
    openai_response_store: Literal[False] = False
    openai_response_service_tier: Literal["auto", "default", "flex", "priority"] = "auto"
    openai_response_reasoning_effort: Literal["none", "low", "medium", "high"] = "low"
    llm_max_evidence_items: int = Field(default=8, ge=1, le=20)
    llm_max_evidence_characters: int = Field(default=24_000, ge=1, le=100_000)
    llm_max_evidence_item_characters: int = Field(default=4_000, ge=1, le=16_000)
    llm_max_prompt_characters: int = Field(default=32_000, ge=1, le=200_000)
    llm_max_answer_characters: int = Field(default=8_000, ge=1, le=32_000)
    llm_max_citations: int = Field(default=20, ge=1, le=100)
    llm_citation_repair_attempts: int = Field(default=1, ge=0, le=2)
    llm_allow_deterministic_fallback: bool = True
    research_enabled: bool = True
    research_max_depth: int = Field(default=2, ge=0, le=5)
    research_max_initial_tasks: int = Field(default=5, ge=1, le=20)
    research_max_total_tasks: int = Field(default=12, ge=1, le=50)
    research_max_child_tasks_per_worker: int = Field(default=2, ge=0, le=5)
    research_max_parallel_workers: int = Field(default=4, ge=1, le=16)
    research_max_retrieval_calls: int = Field(default=16, ge=1, le=100)
    research_max_analysis_calls: int = Field(default=2, ge=0, le=20)
    research_max_llm_calls: int = Field(default=6, ge=1, le=30)
    research_max_evidence_items: int = Field(default=30, ge=1, le=100)
    research_max_total_evidence_characters: int = Field(default=60_000, ge=1, le=500_000)
    research_max_query_characters: int = Field(default=1_000, ge=1, le=4_000)
    research_max_queries_per_task: int = Field(default=4, ge=1, le=20)
    research_max_plan_characters: int = Field(default=12_000, ge=1, le=100_000)
    research_max_execution_seconds: float = Field(default=60, gt=0, le=300)
    research_worker_timeout_seconds: float = Field(default=15, gt=0, le=120)
    research_planner_timeout_seconds: float = Field(default=15, gt=0, le=120)
    research_allow_partial_results: bool = True

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("OLLAMA_BASE_URL must be an HTTP origin without credentials or paths")
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("OLLAMA_BASE_URL contains an invalid port") from error
        if port is not None and not 1 <= port <= 65_535:
            raise ValueError("OLLAMA_BASE_URL contains an invalid port")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_enabled(self) -> Self:
        if self.hybrid_dense_weight + self.hybrid_sparse_weight <= 0:
            raise ValueError("at least one hybrid weight must be positive")
        if self.pinecone_enabled and (
            self.pinecone_api_key is None or not self.pinecone_api_key.get_secret_value()
        ):
            raise ValueError("PINECONE_API_KEY is required when Pinecone is enabled")
        if (
            self.llm_enabled
            and self.llm_provider == "openai"
            and (self.openai_api_key is None or not self.openai_api_key.get_secret_value())
        ):
            raise ValueError("OPENAI_API_KEY is required when the OpenAI LLM provider is enabled")
        parsed_ollama = urlsplit(self.ollama_base_url)
        local_hosts = {"127.0.0.1", "::1", "localhost", "host.docker.internal"}
        if parsed_ollama.hostname not in local_hosts:
            if not self.ollama_allow_remote:
                raise ValueError("remote Ollama requires OLLAMA_ALLOW_REMOTE=true")
            if parsed_ollama.scheme != "https":
                raise ValueError("remote Ollama requires HTTPS")
        unit_seconds = {"s": 1, "m": 60, "h": 3_600}
        if int(self.ollama_keep_alive[:-1]) * unit_seconds[self.ollama_keep_alive[-1]] > 3_600:
            raise ValueError("OLLAMA_KEEP_ALIVE must not exceed one hour")
        if self.langsmith_tracing and (
            self.langsmith_api_key is None or not self.langsmith_api_key.get_secret_value()
        ):
            raise ValueError("LANGSMITH_API_KEY is required when LangSmith tracing is enabled")
        return self

    def selected_llm_model(self) -> str:
        return self.ollama_model if self.llm_provider == "ollama" else self.openai_response_model

    def selected_llm_max_output_tokens(self) -> int:
        return (
            self.ollama_num_predict
            if self.llm_provider == "ollama"
            else self.openai_response_max_output_tokens
        )

    def selected_llm_timeout_seconds(self) -> float:
        return (
            self.ollama_request_timeout_seconds
            if self.llm_provider == "ollama"
            else self.openai_response_timeout_seconds
        )

    def langsmith_api_key_value(self) -> str:
        if self.langsmith_api_key is None:
            raise RetrievalConfigurationError("LangSmith configuration is incomplete")
        return self.langsmith_api_key.get_secret_value()

    def openai_api_key_value(self) -> str:
        if self.openai_api_key is None:
            raise RetrievalConfigurationError("OpenAI configuration is incomplete")
        return self.openai_api_key.get_secret_value()

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
