"""Behavioral tests for failure-isolated, task-local trace spans."""

import asyncio

import pytest
from enterprise_ai.observability.tracing import FakeTraceRecorder, SafeTracer, TraceRecord


@pytest.mark.asyncio
async def test_nested_spans_have_parent_relationship_and_safe_metadata() -> None:
    recorder = FakeTraceRecorder()
    tracer = SafeTracer(recorder)

    async with tracer.span("root", metadata={"request_id": "one", "password": "no"}) as root:
        assert root is not None
        root.update_metadata(
            {
                "route": "r" * 300,
                "authorization": "Bearer secret",
                "raw_evidence": "confidential",
            }
        )
        async with tracer.span("child", "tool"):
            pass

    assert [item.name for item in recorder.records] == ["root", "child"]
    assert recorder.records[1].parent_id == recorder.records[0].run_id
    assert recorder.records[0].metadata == {"request_id": "one", "route": "r" * 256}
    with pytest.raises(TypeError):
        recorder.records[0].metadata["route"] = "unchecked"  # type: ignore[index]
    assert all(item.status == "completed" for item in recorder.records)


@pytest.mark.asyncio
async def test_concurrent_trace_contexts_do_not_leak() -> None:
    recorder = FakeTraceRecorder()
    tracer = SafeTracer(recorder)

    async def invoke(request_id: str) -> None:
        async with tracer.span("root", metadata={"request_id": request_id}) as root:
            assert root is not None
            await asyncio.sleep(0)
            root.update_metadata({"route": f"route-{request_id}"})
            async with tracer.span("child"):
                pass

    await asyncio.gather(invoke("one"), invoke("two"))
    roots = {
        item.run_id: item.metadata["request_id"] for item in recorder.records if not item.parent_id
    }
    children = [item for item in recorder.records if item.parent_id]
    assert len(roots) == 2
    assert {roots[item.parent_id] for item in children} == {"one", "two"}
    assert {
        item.metadata["request_id"]: item.metadata["route"]
        for item in recorder.records
        if not item.parent_id
    } == {"one": "route-one", "two": "route-two"}


class FailingRecorder:
    async def start(self, record: TraceRecord) -> None:
        raise RuntimeError("transport unavailable")

    async def finish(self, record: TraceRecord) -> None:
        raise RuntimeError("transport unavailable")

    async def flush(self) -> None:
        raise RuntimeError("transport unavailable")


@pytest.mark.asyncio
async def test_transport_failure_is_isolated_and_cancellation_propagates() -> None:
    tracer = SafeTracer(FailingRecorder())
    async with tracer.span("root"):
        assert True
    await tracer.flush()

    recorder = FakeTraceRecorder()
    with pytest.raises(asyncio.CancelledError):
        async with SafeTracer(recorder).span("cancelled"):
            raise asyncio.CancelledError
    assert recorder.records[0].status == "cancelled"
