"""FastAPI runtime retrieval-mode selection and failure-boundary tests."""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import pytest
from enterprise_ai.api.runtime import create_api_retriever, create_api_runtime
from enterprise_ai.graph.dependencies import OfflineSparseAdapter
from enterprise_ai.graph.schemas import GraphInput
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import AgentEventType
from enterprise_ai.models.graph import Route
from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.exceptions import RetrievalDependencyError
from enterprise_ai.retrieval.hybrid.retriever import HybridRetrievalService
from pydantic import SecretStr, ValidationError


class FakeGateway:
    async def model_dimension(self, model: str) -> int:
        del model
        return 3

    async def describe_index(self, name: str) -> dict[str, object]:
        return {"name": name, "dimension": 3, "metric": "cosine"}

    async def create_index(
        self,
        *,
        name: str,
        dimension: int,
        metric: str,
        cloud: str,
        region: str,
    ) -> None:
        del name, dimension, metric, cloud, region

    async def upsert(self, records: Sequence[dict[str, Any]], *, namespace: str) -> int:
        del namespace
        return len(records)

    async def fetch(self, ids: Sequence[str], *, namespace: str) -> dict[str, object]:
        del ids, namespace
        return {}

    async def query(
        self,
        *,
        vector: Sequence[float],
        top_k: int,
        namespace: str,
        metadata_filter: dict[str, Any],
        include_metadata: bool,
        include_values: bool,
    ) -> Sequence[dict[str, object]]:
        del (
            vector,
            top_k,
            namespace,
            metadata_filter,
            include_metadata,
            include_values,
        )
        return ()

    async def namespace_count(self, namespace: str) -> int:
        del namespace
        return 0

    async def embed(
        self,
        *,
        model: str,
        inputs: Sequence[str],
        parameters: dict[str, str | int],
    ) -> dict[str, object]:
        del model, inputs, parameters
        return {"data": [{"values": [1.0, 2.0, 3.0]}]}

    async def get_model(self, *, model: str) -> dict[str, object]:
        del model
        return {"default_dimension": 3, "supported_metrics": ["cosine"]}

    async def close(self) -> None:
        return None


class FailingEmbeddings:
    model_name = "safe-fake"

    def __init__(self) -> None:
        self.closed = False

    async def dimension(self) -> int:
        return 3

    async def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        del texts
        raise AssertionError("runtime retrieval must use query embeddings")

    async def embed_query(self, text: str) -> tuple[float, ...]:
        del text
        raise RetrievalDependencyError("private-pinecone-key-marker internal/provider/path")

    async def close(self) -> None:
        self.closed = True


def _hybrid_settings(**updates: object) -> RetrievalSettings:
    values: dict[str, object] = {
        "retrieval_mode": "pinecone_hybrid",
        "pinecone_enabled": True,
        "pinecone_api_key": SecretStr("test-pinecone-key-not-real"),
        "pinecone_dense_dimension": 3,
    }
    values.update(updates)
    return RetrievalSettings.model_validate(values)


def test_api_runtime_selects_sparse_by_default() -> None:
    retriever = create_api_retriever(RetrievalSettings.model_validate({}))

    assert isinstance(retriever, OfflineSparseAdapter)


def test_api_runtime_selects_real_hybrid_stack_when_configured() -> None:
    retriever = create_api_retriever(
        _hybrid_settings(),
        gateway=FakeGateway(),
        embeddings=FailingEmbeddings(),
    )

    assert isinstance(retriever, HybridRetrievalService)


def test_hybrid_mode_requires_enabled_pinecone_and_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL_MODE", "pinecone_hybrid")
    monkeypatch.delenv("PINECONE_ENABLED", raising=False)
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="PINECONE_ENABLED"):
        RetrievalSettings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.setenv("PINECONE_ENABLED", "true")
    with pytest.raises(ValidationError, match="PINECONE_API_KEY"):
        RetrievalSettings(_env_file=None)  # type: ignore[call-arg]


def test_legacy_sparse_environment_alias_remains_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RETRIEVAL_MODE", raising=False)
    monkeypatch.setenv("GRAPH_OFFLINE_RETRIEVAL_MODE", "sparse")

    settings = RetrievalSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.retrieval_mode == "sparse"


@pytest.mark.asyncio
async def test_pinecone_failure_becomes_safe_graph_owned_failure() -> None:
    embeddings = FailingEmbeddings()
    settings = _hybrid_settings(hybrid_allow_partial_results=False)
    runtime = create_api_runtime(
        settings,
        gateway=FakeGateway(),
        embeddings=embeddings,
    )
    graph_input = GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(UserRole.VIEWER),
        user_message="Find the active payment recovery runbook.",
    )

    items = [item async for item in runtime.astream(graph_input)]
    events = [item.event for item in items if item.event is not None]
    output = next(item.output for item in items if item.output is not None)
    serialized = repr(items)
    await runtime.aclose()

    assert output.completion_status is ProcessingStatus.FAILED
    assert output.selected_route is Route.FAILURE
    assert output.response_text == "The request failed safely."
    assert output.evidence == ()
    assert output.citations == ()
    assert events[-1].event_type is AgentEventType.RESPONSE_FAILED
    assert [item.sequence_number for item in events] == list(range(len(events)))
    assert "private-pinecone-key-marker" not in serialized
    assert "internal/provider/path" not in serialized
    assert "test-pinecone-key-not-real" not in serialized
    assert embeddings.closed
