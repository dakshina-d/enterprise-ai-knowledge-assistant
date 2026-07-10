"""Async Pinecone gateway protocol and stable-SDK adapter."""

from collections.abc import Sequence
from typing import Any, NoReturn, Protocol

from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.exceptions import (
    RetrievalAuthenticationError,
    RetrievalDependencyError,
    RetrievalTimeoutError,
    RetrievalTransientError,
)
from enterprise_ai.retrieval.metadata import PineconeMetadata


class VectorRecord(Protocol):
    id: str
    values: Sequence[float]
    metadata: PineconeMetadata


class PineconeGateway(Protocol):
    async def model_dimension(self, model: str) -> int | None: ...

    async def describe_index(self, name: str) -> dict[str, Any] | None: ...

    async def create_index(
        self, *, name: str, dimension: int, metric: str, cloud: str, region: str
    ) -> None: ...

    async def upsert(self, records: Sequence[dict[str, Any]], *, namespace: str) -> int: ...

    async def fetch(self, ids: Sequence[str], *, namespace: str) -> dict[str, Any]: ...

    async def query(
        self,
        *,
        vector: Sequence[float],
        top_k: int,
        namespace: str,
        metadata_filter: dict[str, Any],
        include_metadata: bool,
        include_values: bool,
    ) -> Sequence[Any]: ...

    async def namespace_count(self, namespace: str) -> int: ...

    async def embed(
        self, *, model: str, inputs: Sequence[str], parameters: dict[str, str | int]
    ) -> Any: ...

    async def get_model(self, *, model: str) -> Any: ...

    async def close(self) -> None: ...


class PineconeSdkGateway:
    """Thin adapter; imports the optional provider only when explicitly constructed."""

    def __init__(self, settings: RetrievalSettings) -> None:
        settings.require_enabled()
        try:
            from pinecone import AsyncPinecone

            self._client: Any = AsyncPinecone(api_key=settings.api_key_value())
            self._settings = settings
            self._index: Any = None
        except Exception as error:
            _raise_provider_failure("Pinecone client initialization failed", error)

    async def _data_index(self) -> Any:
        if self._index is None:
            host = self._settings.pinecone_index_host
            if not host:
                description = await self.describe_index(self._settings.pinecone_index_name)
                host = str(description.get("host", "")) if description else ""
            if not host:
                raise RetrievalDependencyError("configured Pinecone index has no ready host")
            self._index = await self._client.index(host=host)
        return self._index

    async def model_dimension(self, model: str) -> int | None:
        info = await self.get_model(model=model)
        value = (
            _value(info, "default_dimension")
            or _value(info, "dimension")
            or _value(info, "output_dimension")
        )
        return int(value) if isinstance(value, int | float) and int(value) > 0 else None

    async def describe_index(self, name: str) -> dict[str, Any] | None:
        try:
            value = await self._client.indexes.describe(name)
            status = _value(value, "status")
            return {
                "name": _value(value, "name"),
                "dimension": _value(value, "dimension"),
                "metric": _value(value, "metric"),
                "host": _value(value, "host"),
                "status": {
                    "ready": bool(_value(status, "ready")),
                    "state": _value(status, "state"),
                },
            }
        except Exception as error:
            if "not found" in str(error).lower() or "404" in str(error):
                return None
            _raise_provider_failure("Pinecone index description failed", error)

    async def create_index(
        self, *, name: str, dimension: int, metric: str, cloud: str, region: str
    ) -> None:
        try:
            from pinecone import ServerlessSpec

            await self._client.indexes.create(
                name=name,
                dimension=dimension,
                metric=metric,
                vector_type="dense",
                spec=ServerlessSpec(cloud=cloud, region=region),
                timeout=-1,
            )
        except Exception as error:
            _raise_provider_failure("Pinecone index creation failed", error)

    async def upsert(self, records: Sequence[dict[str, Any]], *, namespace: str) -> int:
        try:
            response = await (await self._data_index()).upsert(
                vectors=list(records), namespace=namespace
            )
            return int(_value(response, "upserted_count") or 0)
        except Exception as error:
            _raise_provider_failure("Pinecone upsert failed", error)

    async def fetch(self, ids: Sequence[str], *, namespace: str) -> dict[str, Any]:
        try:
            response = await (await self._data_index()).fetch(ids=list(ids), namespace=namespace)
            return _dictionary(_value(response, "vectors") or {})
        except Exception as error:
            _raise_provider_failure("Pinecone fetch failed", error)

    async def query(self, **kwargs: Any) -> Sequence[Any]:
        try:
            response = await (await self._data_index()).query(
                filter=kwargs.pop("metadata_filter"), **kwargs
            )
            return _value(response, "matches") or ()
        except Exception as error:
            _raise_provider_failure("Pinecone query failed", error)

    async def namespace_count(self, namespace: str) -> int:
        response = await (await self._data_index()).describe_index_stats()
        namespaces = _value(response, "namespaces") or {}
        item = namespaces.get(namespace) if isinstance(namespaces, dict) else None
        return int(_value(item, "vector_count") or 0)

    async def embed(self, **kwargs: Any) -> Any:
        return await self._client.inference.embed(**kwargs)

    async def get_model(self, *, model: str) -> Any:
        return await self._client.inference.get_model(model=model)

    async def close(self) -> None:
        if self._index is not None:
            await self._index.close()
        await self._client.close()


def _value(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _dictionary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _raise_provider_failure(message: str, error: Exception) -> NoReturn:
    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    name = type(error).__name__.lower()
    if status in {401, 403} or "unauthorized" in name or "forbidden" in name:
        raise RetrievalAuthenticationError(message) from error
    if "timeout" in name:
        raise RetrievalTimeoutError(message) from error
    if status == 429 or (isinstance(status, int) and status >= 500) or "connection" in name:
        raise RetrievalTransientError(message) from error
    raise RetrievalDependencyError(message) from error
