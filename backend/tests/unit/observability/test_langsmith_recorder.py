"""Regression tests for the asynchronous manual LangSmith recorder."""

import asyncio
import threading

import pytest
from enterprise_ai.observability import tracing
from enterprise_ai.observability.tracing import (
    LangSmithTraceRecorder,
    SafeTracer,
    TraceRecord,
)
from enterprise_ai.retrieval.config import RetrievalSettings


class RecordingClient:
    def __init__(self, **kwargs: object) -> None:
        self.options = kwargs
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object], int]] = []

    def create_run(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("create", args, kwargs, threading.get_ident()))

    def update_run(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("update", args, kwargs, threading.get_ident()))

    def flush(self) -> None:
        self.calls.append(("flush", (), {}, threading.get_ident()))


def enabled_settings() -> RetrievalSettings:
    return RetrievalSettings(langsmith_tracing=True, langsmith_api_key="test-only-key")


@pytest.mark.asyncio
async def test_manual_recorder_uses_consistent_ids_without_blocking_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RecordingClient()
    monkeypatch.setattr(tracing, "Client", lambda **kwargs: _configure(client, kwargs))
    recorder = LangSmithTraceRecorder(enabled_settings())
    event_loop_thread = threading.get_ident()

    async with SafeTracer(recorder).span("root") as root:
        assert root is not None
        root.update_metadata({"route": "python_analysis", "raw_query": "secret"})
        async with SafeTracer(recorder).span("child") as child:
            pass
    await recorder.flush()

    assert child is not None
    assert client.options["auto_batch_tracing"] is False
    creates = [call for call in client.calls if call[0] == "create"]
    updates = [call for call in client.calls if call[0] == "update"]
    assert [call[2]["id"] for call in creates] == [root.run_id, child.run_id]
    assert all("run_id" not in call[2] for call in creates)
    assert [call[1][0] for call in updates] == [child.run_id, root.run_id]
    assert creates[0][2]["parent_run_id"] is None
    assert creates[1][2]["parent_run_id"] == root.run_id
    assert [call[0] for call in client.calls] == [
        "create",
        "create",
        "update",
        "update",
        "flush",
    ]
    assert all(call[3] != event_loop_thread for call in client.calls)
    root_update_metadata = updates[-1][2]["extra"]
    assert isinstance(root_update_metadata, dict)
    assert root_update_metadata["metadata"]["route"] == "python_analysis"
    assert "raw_query" not in root_update_metadata["metadata"]


def _configure(client: RecordingClient, options: dict[str, object]) -> RecordingClient:
    client.options = options
    return client


class AwaitedRecorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start(self, record: TraceRecord) -> None:
        await asyncio.sleep(0)
        self.calls.append(f"started:{record.name}")

    async def finish(self, record: TraceRecord) -> None:
        await asyncio.sleep(0)
        self.calls.append(f"finished:{record.name}:{record.status}")

    async def flush(self) -> None:
        await asyncio.sleep(0)
        self.calls.append("flushed")


@pytest.mark.asyncio
async def test_safe_tracer_awaits_start_finish_and_flush() -> None:
    recorder = AwaitedRecorder()
    tracer = SafeTracer(recorder)

    async with tracer.span("root"):
        assert recorder.calls == ["started:root"]
    assert recorder.calls == ["started:root", "finished:root:completed"]

    await tracer.flush()
    assert recorder.calls[-1] == "flushed"


class SelectivelyFailingClient(RecordingClient):
    def __init__(self, failure: str) -> None:
        super().__init__()
        self.failure = failure

    def create_run(self, *args: object, **kwargs: object) -> None:
        if self.failure == "start":
            raise RuntimeError("sensitive transport detail")
        super().create_run(*args, **kwargs)

    def update_run(self, *args: object, **kwargs: object) -> None:
        if self.failure == "finish":
            raise RuntimeError("sensitive transport detail")
        super().update_run(*args, **kwargs)

    def flush(self) -> None:
        if self.failure == "flush":
            raise RuntimeError("sensitive transport detail")
        super().flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["start", "finish", "flush"])
async def test_langsmith_failures_are_isolated_and_safely_logged(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = SelectivelyFailingClient(failure)
    monkeypatch.setattr(tracing, "Client", lambda **kwargs: _configure(client, kwargs))
    tracer = SafeTracer(LangSmithTraceRecorder(enabled_settings()))

    async with tracer.span("root"):
        pass
    await tracer.flush()

    assert "sensitive transport detail" not in caplog.text
    expected = {
        "start": "Trace start failed",
        "finish": "Trace finish failed",
        "flush": "Trace flush failed",
    }
    assert expected[failure] in caplog.text
