"""Async dense-embedding abstraction and Pinecone Inference adapter."""

import math
from collections.abc import Sequence
from typing import Any, Protocol

from enterprise_ai.retrieval.exceptions import (
    RetrievalDataIntegrityError,
    RetrievalDependencyError,
    RetrievalValidationError,
)


class EmbeddingProvider(Protocol):
    model_name: str

    async def dimension(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...

    async def embed_query(self, text: str) -> tuple[float, ...]: ...

    async def close(self) -> None: ...


class InferenceClient(Protocol):
    async def embed(
        self, *, model: str, inputs: Sequence[str], parameters: dict[str, str | int]
    ) -> Any: ...

    async def get_model(self, *, model: str) -> Any: ...

    async def close(self) -> None: ...


def validate_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
    expected_dimension: int | None = None,
) -> tuple[tuple[float, ...], ...]:
    if len(vectors) != expected_count:
        raise RetrievalDataIntegrityError("embedding result count does not match input count")
    normalized: list[tuple[float, ...]] = []
    dimension = expected_dimension
    for raw in vectors:
        vector = tuple(float(value) for value in raw)
        if not vector or any(not math.isfinite(value) for value in vector):
            raise RetrievalDataIntegrityError("embedding vector is empty or non-finite")
        dimension = dimension or len(vector)
        if len(vector) != dimension:
            raise RetrievalDataIntegrityError("embedding vector dimension mismatch")
        normalized.append(vector)
    return tuple(normalized)


class PineconeInferenceEmbeddingProvider:
    def __init__(
        self,
        client: InferenceClient,
        model_name: str,
        *,
        selected_dimension: int,
        metric: str,
        maximum_input_chars: int,
    ) -> None:
        self._client = client
        self.model_name = model_name
        self._maximum_input_chars = maximum_input_chars
        self._selected_dimension = selected_dimension
        self._metric = metric
        self._dimension: int | None = None

    async def dimension(self) -> int:
        if self._dimension is not None:
            return self._dimension
        try:
            info = await self._client.get_model(model=self.model_name)
            default = (
                _field(info, "default_dimension")
                or _field(info, "dimension")
                or _field(info, "output_dimension")
            )
            supported = _field(info, "supported_dimensions")
            if isinstance(supported, Sequence) and not isinstance(supported, str):
                supported_values = {int(value) for value in supported}
                if self._selected_dimension not in supported_values:
                    raise RetrievalDataIntegrityError(
                        "configured embedding dimension is unsupported by the model"
                    )
            elif default != self._selected_dimension:
                raise RetrievalDataIntegrityError(
                    "embedding model does not confirm the configured dimension"
                )
            metrics = _field(info, "supported_metrics")
            if isinstance(metrics, Sequence) and not isinstance(metrics, str):
                normalized_metrics = {str(value).casefold() for value in metrics}
                if self._metric.casefold() not in normalized_metrics:
                    raise RetrievalDataIntegrityError(
                        "configured metric is unsupported by the embedding model"
                    )
            self._dimension = self._selected_dimension
            probe = await self.embed_query("dimension validation probe")
            if len(probe) != self._selected_dimension:
                raise RetrievalDataIntegrityError("embedding probe dimension mismatch")
            return self._dimension
        except RetrievalDataIntegrityError:
            raise
        except Exception as error:
            raise RetrievalDependencyError("embedding model information is unavailable") from error

    async def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return await self._embed(texts, input_type="passage")

    async def embed_query(self, text: str) -> tuple[float, ...]:
        return (await self._embed((text,), input_type="query"))[0]

    async def _embed(
        self, texts: Sequence[str], *, input_type: str
    ) -> tuple[tuple[float, ...], ...]:
        if not texts or any(not text.strip() for text in texts):
            raise RetrievalValidationError("embedding input must not be empty")
        if any(len(text) > self._maximum_input_chars for text in texts):
            raise RetrievalValidationError("embedding input exceeds configured maximum")
        try:
            response = await self._client.embed(
                model=self.model_name,
                inputs=texts,
                parameters={
                    "input_type": input_type,
                    "truncate": "END",
                    "dimension": self._selected_dimension,
                },
            )
            data = _field(response, "data")
            if not isinstance(data, Sequence):
                raise RetrievalDataIntegrityError("embedding response is malformed")
            vectors = [_field(item, "values") for item in data]
            if any(not isinstance(vector, Sequence) for vector in vectors):
                raise RetrievalDataIntegrityError("embedding response contains no dense vector")
            validated = validate_vectors(
                vectors, expected_count=len(texts), expected_dimension=self._dimension
            )
            self._dimension = len(validated[0])
            return validated
        except (RetrievalValidationError, RetrievalDataIntegrityError):
            raise
        except Exception as error:
            raise RetrievalDependencyError("embedding provider request failed") from error

    async def close(self) -> None:
        await self._client.close()


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
