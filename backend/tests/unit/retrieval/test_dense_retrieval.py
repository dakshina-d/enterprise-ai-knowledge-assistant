"""Offline tests for dense embedding, indexing, filtering, and retrieval."""

import asyncio
import json
import math
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.dense_retriever import DenseRetrievalService
from enterprise_ai.retrieval.embeddings import (
    PineconeInferenceEmbeddingProvider,
    validate_vectors,
)
from enterprise_ai.retrieval.evaluation import assessment_principal, evaluate_dense_retrieval
from enterprise_ai.retrieval.exceptions import (
    RetrievalDataIntegrityError,
    RetrievalTransientError,
    RetrievalValidationError,
)
from enterprise_ai.retrieval.filters import DenseQueryFilters, build_authorization_filter
from enterprise_ai.retrieval.indexer import DenseIndexer, load_current_chunks
from enterprise_ai.retrieval.metadata import chunk_metadata
from enterprise_ai.retrieval.pinecone_client import PineconeSdkGateway
from enterprise_ai.retrieval.retry import retry_delay, with_retries
from enterprise_ai_ingestion.config import default_config
from enterprise_ai_ingestion.pipeline import IngestionPipeline
from pydantic import SecretStr, ValidationError


def _settings(**changes: object) -> RetrievalSettings:
    values: dict[str, object] = {
        "pinecone_enabled": True,
        "pinecone_api_key": SecretStr("test-key-not-a-real-secret"),
        "pinecone_max_retries": 1,
        "pinecone_retry_base_seconds": 0.001,
    }
    values.update(changes)
    return RetrievalSettings(_env_file=None, **values)


def _artifact_settings(tmp_path: Path, **changes: object) -> RetrievalSettings:
    bundle = asyncio.run(IngestionPipeline(default_config()).expected_bundle())
    output = tmp_path / "processed"
    output.mkdir()
    for name, content in bundle.files.items():
        (output / name).write_bytes(content)
    return _settings(
        ingestion_manifest_path=output / "ingestion_manifest.json",
        ingestion_chunks_path=output / "chunks.jsonl",
        **changes,
    )


class FakeEmbeddings:
    model_name = "fake-dense-v1"

    def __init__(self, dimension: int = 3) -> None:
        self.output_dimension = dimension
        self.document_calls: list[tuple[str, ...]] = []
        self.query_calls: list[str] = []
        self.closed = False

    async def dimension(self) -> int:
        return self.output_dimension

    async def embed_documents(self, texts: list[str]) -> tuple[tuple[float, ...], ...]:
        self.document_calls.append(tuple(texts))
        return tuple(
            tuple(float(index + 1) for index in range(self.output_dimension)) for _ in texts
        )

    async def embed_query(self, text: str) -> tuple[float, ...]:
        self.query_calls.append(text)
        return tuple(float(index + 1) for index in range(self.output_dimension))

    async def close(self) -> None:
        self.closed = True


class FakeGateway:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.matches: list[dict[str, Any]] = []
        self.query_arguments: dict[str, Any] = {}
        self.upsert_attempts = 0
        self.transient_once = False
        self.closed = False
        self.dimension = 3
        self.metric = "cosine"

    async def describe_index(self, name: str) -> dict[str, Any]:
        return {
            "name": name,
            "dimension": self.dimension,
            "metric": self.metric,
            "status": {"ready": True},
        }

    async def create_index(self, **kwargs: Any) -> None:
        raise AssertionError("existing fake index must not be recreated")

    async def upsert(self, records: list[dict[str, Any]], *, namespace: str) -> int:
        self.upsert_attempts += 1
        if self.transient_once and self.upsert_attempts == 1:
            raise RetrievalTransientError("temporary")
        self.records.update({record["id"]: record for record in records})
        return len(records)

    async def fetch(self, ids: list[str], *, namespace: str) -> dict[str, Any]:
        return {
            identifier: self.records[identifier] for identifier in ids if identifier in self.records
        }

    async def query(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.query_arguments = kwargs
        return self.matches

    async def namespace_count(self, namespace: str) -> int:
        return len(self.records)

    async def model_dimension(self, model: str) -> int:
        return 3

    async def embed(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def get_model(self, *, model: str) -> Any:
        return {"dimension": 3}

    async def close(self) -> None:
        self.closed = True


class FakeInference:
    def __init__(self) -> None:
        self.modes: list[str] = []
        self.parameters: list[dict[str, str | int]] = []
        self.closed = False

    async def embed(self, **kwargs: Any) -> dict[str, Any]:
        self.modes.append(kwargs["parameters"]["input_type"])
        self.parameters.append(kwargs["parameters"])
        return {"data": [{"values": [1.0, 2.0, 3.0]} for _ in kwargs["inputs"]]}

    async def get_model(self, *, model: str) -> dict[str, Any]:
        return {
            "default_dimension": 3,
            "supported_dimensions": [2, 3],
            "supported_metrics": ["cosine", "dotproduct"],
        }

    async def close(self) -> None:
        self.closed = True


def test_disabled_configuration_needs_no_secret_and_enabled_does() -> None:
    assert not RetrievalSettings(_env_file=None).pinecone_enabled
    with pytest.raises(ValidationError):
        RetrievalSettings(_env_file=None, pinecone_enabled=True)
    with pytest.raises(ValidationError):
        RetrievalSettings(_env_file=None, pinecone_namespace="unsafe namespace")
    with pytest.raises(ValidationError):
        RetrievalSettings(_env_file=None, pinecone_query_top_k=0)


def test_embedding_modes_order_dimension_and_finite_validation() -> None:
    inference = FakeInference()
    provider = PineconeInferenceEmbeddingProvider(
        inference,
        "fake",
        selected_dimension=3,
        metric="cosine",
        maximum_input_chars=100,
    )
    documents = asyncio.run(provider.embed_documents(["one", "two"]))
    query = asyncio.run(provider.embed_query("query"))
    assert len(documents) == 2 and query == (1.0, 2.0, 3.0)
    assert inference.modes == ["passage", "query"]
    assert all(parameters["dimension"] == 3 for parameters in inference.parameters)
    assert validate_vectors([[1.0, 2.0]], expected_count=1) == ((1.0, 2.0),)
    with pytest.raises(RetrievalDataIntegrityError):
        validate_vectors([[math.nan]], expected_count=1)
    with pytest.raises(RetrievalDataIntegrityError):
        validate_vectors([[]], expected_count=1)
    with pytest.raises(RetrievalDataIntegrityError):
        validate_vectors([[1.0]], expected_count=2)


def test_embedding_dimension_is_explicit_supported_and_probe_confirmed() -> None:
    inference = FakeInference()
    provider = PineconeInferenceEmbeddingProvider(
        inference,
        "fake",
        selected_dimension=3,
        metric="cosine",
        maximum_input_chars=100,
    )
    assert asyncio.run(provider.dimension()) == 3
    assert inference.modes == ["query"]
    unsupported = PineconeInferenceEmbeddingProvider(
        inference,
        "fake",
        selected_dimension=4,
        metric="cosine",
        maximum_input_chars=100,
    )
    with pytest.raises(RetrievalDataIntegrityError):
        asyncio.run(unsupported.dimension())


@pytest.mark.parametrize(
    ("role", "levels"),
    [
        (UserRole.VIEWER, {"public", "internal"}),
        (UserRole.ANALYST, {"public", "internal", "confidential"}),
        (UserRole.ADMINISTRATOR, {level.value for level in AccessLevel}),
    ],
)
def test_mandatory_filter_uses_central_policy(role: UserRole, levels: set[str]) -> None:
    compiled = build_authorization_filter(assessment_principal(role), "a" * 64)
    clauses = compiled["$and"]
    assert {"build_fingerprint": {"$eq": "a" * 64}} in clauses
    assert {"allowed_roles": {"$in": [role.value]}} in clauses
    assert {"access_level": {"$in": sorted(levels)}} in clauses


def test_optional_filters_narrow_and_reject_access_broadening() -> None:
    filters = DenseQueryFilters(
        departments=("payments",),
        created_from=date(2026, 1, 1),
        tags=("incident",),
        access_levels=(AccessLevel.INTERNAL,),
    )
    compiled = build_authorization_filter(assessment_principal(UserRole.VIEWER), "b" * 64, filters)
    assert {"department": {"$in": ["payments"]}} in compiled["$and"]
    assert any("created_day" in clause for clause in compiled["$and"])
    with pytest.raises(ValueError):
        build_authorization_filter(
            assessment_principal(UserRole.VIEWER),
            "b" * 64,
            DenseQueryFilters(access_levels=(AccessLevel.RESTRICTED,)),
        )
    with pytest.raises(ValidationError):
        DenseQueryFilters.model_validate({"build_fingerprint": "override"})


def test_metadata_is_flat_bounded_and_complete(tmp_path: Path) -> None:
    manifest, chunks = load_current_chunks(_artifact_settings(tmp_path))
    metadata = chunk_metadata(
        chunks[0], build_fingerprint=manifest.build_fingerprint, maximum_bytes=35_000
    )
    assert metadata["build_fingerprint"] == manifest.build_fingerprint
    assert isinstance(metadata["allowed_roles"], list)
    assert isinstance(metadata["created_day"], float)
    assert not any(isinstance(value, dict) for value in metadata.values())
    with pytest.raises(RetrievalValidationError):
        chunk_metadata(chunks[0], build_fingerprint=manifest.build_fingerprint, maximum_bytes=10)


def test_indexer_loads_all_chunks_batches_retries_and_is_idempotent(tmp_path: Path) -> None:
    settings = _artifact_settings(
        tmp_path, pinecone_embed_batch_size=20, pinecone_upsert_batch_size=25
    )
    embeddings = FakeEmbeddings()
    gateway = FakeGateway()
    gateway.transient_once = True
    indexer = DenseIndexer(settings, embeddings, gateway)
    first = asyncio.run(indexer.index())
    second = asyncio.run(indexer.index())
    assert first.expected_count == first.indexed_count == 83
    assert second.indexed_count == 83 and len(gateway.records) == 83
    assert gateway.upsert_attempts > 8
    assert all(
        "security_fixtures" not in record["metadata"]["source_file"]
        for record in gateway.records.values()
    )


def test_index_check_detects_identity_fingerprint_metadata_and_index_mismatch(
    tmp_path: Path,
) -> None:
    settings = _artifact_settings(tmp_path)
    embeddings = FakeEmbeddings()
    gateway = FakeGateway()
    indexer = DenseIndexer(settings, embeddings, gateway)
    asyncio.run(indexer.index())
    identifier = next(iter(gateway.records))
    record = gateway.records.pop(identifier)
    with pytest.raises(RetrievalDataIntegrityError):
        asyncio.run(indexer.verify())
    gateway.records[identifier] = record
    record["metadata"]["build_fingerprint"] = "0" * 64
    with pytest.raises(RetrievalDataIntegrityError):
        asyncio.run(indexer.verify())
    record["metadata"]["build_fingerprint"] = load_current_chunks(settings)[0].build_fingerprint
    record["metadata"].pop("allowed_roles")
    with pytest.raises(RetrievalDataIntegrityError):
        asyncio.run(indexer.verify())
    gateway.dimension = 4
    with pytest.raises(RetrievalDataIntegrityError):
        asyncio.run(indexer.verify())
    gateway.dimension = 3
    gateway.metric = "dotproduct"
    with pytest.raises(RetrievalDataIntegrityError):
        asyncio.run(indexer.verify())


def _match_for_role(
    settings: RetrievalSettings, access: AccessLevel, roles: list[str]
) -> dict[str, Any]:
    manifest, chunks = load_current_chunks(settings)
    chunk = chunks[0]
    metadata = chunk_metadata(
        chunk, build_fingerprint=manifest.build_fingerprint, maximum_bytes=35_000
    )
    metadata["access_level"] = access.value
    metadata["allowed_roles"] = roles
    return {"id": str(chunk.chunk_id), "score": -0.25, "metadata": metadata}


def test_retriever_enforces_filters_drops_unauthorized_and_never_requests_vectors(
    tmp_path: Path,
) -> None:
    settings = _artifact_settings(tmp_path)
    embeddings = FakeEmbeddings()
    gateway = FakeGateway()
    gateway.matches = [
        _match_for_role(settings, AccessLevel.INTERNAL, ["viewer"]),
        _match_for_role(settings, AccessLevel.CONFIDENTIAL, ["analyst"]),
        {"id": "malformed", "score": 0.5, "metadata": {}},
    ]
    service = DenseRetrievalService(settings, embeddings, gateway)
    result = asyncio.run(
        service.retrieve(assessment_principal(UserRole.VIEWER), "payment gateway", top_k=5)
    )
    assert len(embeddings.query_calls) == 1
    assert len(result.evidence) == 1
    assert result.evidence[0].dense_score == -0.25
    assert result.dropped_unauthorized == 1 and result.malformed_results == 1
    assert gateway.query_arguments["include_values"] is False
    assert gateway.query_arguments["namespace"] == settings.pinecone_namespace
    assert gateway.query_arguments["metadata_filter"]["$and"]


@pytest.mark.parametrize(
    ("role", "access", "allowed_roles"),
    [
        (UserRole.VIEWER, AccessLevel.CONFIDENTIAL, ["viewer"]),
        (UserRole.ANALYST, AccessLevel.RESTRICTED, ["analyst"]),
        (UserRole.ADMINISTRATOR, AccessLevel.RESTRICTED, ["analyst"]),
    ],
)
def test_provider_results_excluded_by_local_authorization(
    tmp_path: Path, role: UserRole, access: AccessLevel, allowed_roles: list[str]
) -> None:
    settings = _artifact_settings(tmp_path)
    gateway = FakeGateway()
    gateway.matches = [_match_for_role(settings, access, allowed_roles)]
    result = asyncio.run(
        DenseRetrievalService(settings, FakeEmbeddings(), gateway).retrieve(
            assessment_principal(role), "safe query"
        )
    )
    assert not result.evidence
    assert result.dropped_unauthorized == 1


def test_stale_missing_and_malformed_authorization_metadata_are_excluded(
    tmp_path: Path,
) -> None:
    settings = _artifact_settings(tmp_path)
    stale = _match_for_role(settings, AccessLevel.INTERNAL, ["viewer"])
    stale["metadata"]["build_fingerprint"] = "0" * 64
    missing_role = _match_for_role(settings, AccessLevel.INTERNAL, ["viewer"])
    missing_role["metadata"].pop("allowed_roles")
    malformed_access = _match_for_role(settings, AccessLevel.INTERNAL, ["viewer"])
    malformed_access["metadata"]["access_level"] = "unknown"
    gateway = FakeGateway()
    gateway.matches = [stale, missing_role, malformed_access]
    result = asyncio.run(
        DenseRetrievalService(settings, FakeEmbeddings(), gateway).retrieve(
            assessment_principal(UserRole.VIEWER), "safe query"
        )
    )
    assert not result.evidence
    assert result.malformed_results == 3


def test_retry_is_bounded_deterministic_and_cancellation_propagates() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def fail() -> None:
        nonlocal attempts
        attempts += 1
        raise RetrievalTransientError("temporary")

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    with pytest.raises(RetrievalTransientError):
        asyncio.run(with_retries(fail, maximum_retries=2, base_seconds=0.1, sleep=record_sleep))
    assert attempts == 3 and sleeps == [retry_delay(0, 0.1), retry_delay(1, 0.1)]

    async def cancel() -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(with_retries(cancel, maximum_retries=2, base_seconds=0.1))


def test_sdk_gateway_awaits_async_index_and_closes_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    import pinecone

    class FakeIndex:
        def __init__(self) -> None:
            self.closed = False

        async def upsert(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(upserted_count=1)

        async def close(self) -> None:
            self.closed = True

    class FakeIndexes:
        async def describe(self, name: str) -> SimpleNamespace:
            return SimpleNamespace(
                name=name,
                host="safe.example",
                dimension=3,
                metric="cosine",
                status=SimpleNamespace(ready=True, state="Ready"),
            )

    class FakeControl:
        instance: "FakeControl"

        def __init__(self, **_kwargs: object) -> None:
            FakeControl.instance = self
            self.indexes = FakeIndexes()
            self.index_client = FakeIndex()
            self.index_awaited = False
            self.closed = False

        async def index(self, **_kwargs: object) -> FakeIndex:
            self.index_awaited = True
            return self.index_client

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(pinecone, "AsyncPinecone", FakeControl)
    gateway = PineconeSdkGateway(_settings(pinecone_index_host="safe.example"))
    description = asyncio.run(gateway.describe_index("test-index"))
    count = asyncio.run(
        gateway.upsert([{"id": "one", "values": [1.0], "metadata": {}}], namespace="test")
    )
    asyncio.run(gateway.close())
    assert count == 1
    assert description == {
        "name": "test-index",
        "dimension": 3,
        "metric": "cosine",
        "host": "safe.example",
        "status": {"ready": True, "state": "Ready"},
    }
    assert FakeControl.instance.index_awaited
    assert FakeControl.instance.index_client.closed
    assert FakeControl.instance.closed


def test_dense_evaluation_computes_document_level_metrics(tmp_path: Path) -> None:
    relevant_id = UUID("df41b181-7c96-5c0d-a410-2104b14fd040")
    questions = tmp_path / "questions.json"
    questions.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question": "payment messages",
                    "expected_route": "simple_retrieval",
                    "required_role": "viewer",
                    "relevant_document_ids": [str(relevant_id)],
                    "expected_access_outcome": "allow",
                }
            ]
        )
    )

    class FakeService:
        async def retrieve(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                evidence=(SimpleNamespace(document_id=relevant_id, source_file="safe.md"),),
                dropped_unauthorized=0,
                malformed_results=0,
            )

    output = tmp_path / "result.json"
    report = asyncio.run(
        evaluate_dense_retrieval(FakeService(), questions_path=questions, output_path=output)  # type: ignore[arg-type]
    )
    assert report["recall_at_1"] == 1.0
    assert report["mean_reciprocal_rank"] == 1.0
    assert output.is_file()
