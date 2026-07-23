"""Failure-isolated tracing with explicit safe payloads."""

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, Protocol
from uuid import UUID, uuid4

from langsmith import Client

from enterprise_ai.observability.sanitization import sanitize_metadata
from enterprise_ai.retrieval.config import RetrievalSettings

LOGGER = logging.getLogger(__name__)
RunType = Literal["tool", "chain", "llm", "retriever", "embedding", "prompt", "parser"]
SafeMetadata = dict[str, str | int | float | bool | None]


@dataclass
class TraceRecord:
    run_id: UUID
    parent_id: UUID | None
    name: str
    run_type: RunType
    _metadata: SafeMetadata
    status: str = "running"
    error_category: str | None = None

    @property
    def metadata(self) -> Mapping[str, str | int | float | bool | None]:
        """Expose validated metadata without permitting unchecked mutation."""
        return MappingProxyType(self._metadata)

    def update_metadata(self, values: Mapping[str, object]) -> None:
        """Merge allowlisted, bounded scalar metadata into this span."""
        self._metadata.update(sanitize_metadata(values))


class TraceRecorder(Protocol):
    async def start(self, record: TraceRecord) -> None: ...
    async def finish(self, record: TraceRecord) -> None: ...
    async def flush(self) -> None: ...


@dataclass
class FakeTraceRecorder:
    records: list[TraceRecord] = field(default_factory=list)

    async def start(self, record: TraceRecord) -> None:
        self.records.append(record)

    async def finish(self, record: TraceRecord) -> None:
        del record

    async def flush(self) -> None:
        return None


class LangSmithTraceRecorder:
    def __init__(self, settings: RetrievalSettings) -> None:
        # Manual parent-child runs require deterministic create-before-update ordering.
        self.client = Client(
            api_url=settings.langsmith_endpoint,
            api_key=settings.langsmith_api_key_value(),
            workspace_id=settings.langsmith_workspace_id,
            auto_batch_tracing=False,
            hide_inputs=True,
            hide_outputs=True,
            omit_traced_runtime_info=True,
            tracing_error_callback=lambda _error: None,
        )
        self.project = settings.langsmith_project

    async def start(self, record: TraceRecord) -> None:
        await asyncio.to_thread(
            self.client.create_run,
            record.name,
            {},
            record.run_type,
            id=record.run_id,
            parent_run_id=record.parent_id,
            project_name=self.project,
            extra={"metadata": dict(record.metadata)},
            tags=["enterprise-ai", "privacy-safe"],
        )

    async def finish(self, record: TraceRecord) -> None:
        await asyncio.to_thread(
            self.client.update_run,
            record.run_id,
            end_time=datetime.now(UTC),
            error=record.error_category,
            outputs={},
            extra={"metadata": {**record.metadata, "status": record.status}},
        )

    async def flush(self) -> None:
        await asyncio.to_thread(self.client.flush)


_current_run: ContextVar[UUID | None] = ContextVar("enterprise_ai_trace_run", default=None)


class SafeTracer:
    def __init__(self, recorder: TraceRecorder | None = None) -> None:
        self.recorder = recorder

    @property
    def enabled(self) -> bool:
        return self.recorder is not None

    @asynccontextmanager
    async def span(
        self,
        name: str,
        run_type: RunType = "chain",
        metadata: Mapping[str, object] | None = None,
    ) -> AsyncIterator[TraceRecord | None]:
        if self.recorder is None:
            yield None
            return
        record = TraceRecord(
            uuid4(), _current_run.get(), name, run_type, sanitize_metadata(metadata or {})
        )
        token = _current_run.set(record.run_id)
        try:
            try:
                await self.recorder.start(record)
            except Exception:
                LOGGER.warning("Trace start failed; application execution will continue")
            yield record
        except asyncio.CancelledError:
            record.status = "cancelled"
            raise
        except Exception as error:
            record.status = "failed"
            record.error_category = type(error).__name__[:100]
            raise
        else:
            record.status = "completed"
        finally:
            try:
                await self.recorder.finish(record)
            except Exception:
                LOGGER.warning("Trace finish failed; application execution will continue")
            _current_run.reset(token)

    async def flush(self) -> None:
        if self.recorder is not None:
            try:
                await self.recorder.flush()
            except Exception:
                LOGGER.warning("Trace flush failed; application shutdown will continue")


def create_tracer(settings: RetrievalSettings) -> SafeTracer:
    return SafeTracer(LangSmithTraceRecorder(settings) if settings.langsmith_tracing else None)
