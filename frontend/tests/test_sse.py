"""Incremental SSE parsing and stream-invariant tests."""

from uuid import uuid4

import pytest
from enterprise_ai.graph.schemas import GraphOutput

from frontend.enterprise_ai_frontend.errors import SSEProtocolError
from frontend.enterprise_ai_frontend.sse import (
    RawSSEEvent,
    SSEParser,
    StreamContractValidator,
    decode_envelope,
)
from frontend.tests.conftest import envelope, frame


def test_parser_handles_multiple_partial_utf8_events(
    graph_output: GraphOutput,
) -> None:
    started = envelope(
        sequence=0,
        event_type="stream.started",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
    )
    completed = envelope(
        sequence=1,
        event_type="response.completed",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
        output=graph_output,
    )
    payload = b": keepalive\r\n\r\n" + frame(started) + frame(completed)
    parser = SSEParser()
    raw: list[RawSSEEvent] = []
    for byte in payload:
        raw.extend(parser.feed(bytes([byte])))
    parser.finish()

    decoded = [decode_envelope(item) for item in raw]
    assert [item.event_type for item in decoded] == [
        "stream.started",
        "response.completed",
    ]
    assert decoded[-1].response == graph_output


def test_parser_supports_multiline_data_and_utf8() -> None:
    parser = SSEParser()
    events = parser.feed('event: note\nid: one\ndata: {"message":\ndata: "café"}\n\n'.encode())
    parser.finish()
    assert events == (RawSSEEvent(event="note", event_id="one", data='{"message":\n"café"}'),)


@pytest.mark.parametrize(
    "payload",
    [
        b"event: note\ndata: {}\n",
        b"event: note\ndata: \xff\n\n",
        b"event: note\nid: bad\x00id\ndata: {}\n\n",
    ],
)
def test_parser_rejects_incomplete_or_invalid_frames(payload: bytes) -> None:
    parser = SSEParser()
    with pytest.raises(SSEProtocolError):
        parser.feed(payload)
        parser.finish()


def test_parser_rejects_oversized_event() -> None:
    parser = SSEParser(maximum_event_bytes=1_024)
    with pytest.raises(SSEProtocolError):
        parser.feed(b"data: " + b"x" * 2_000)


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(SSEProtocolError):
        decode_envelope(RawSSEEvent(event="message", event_id="id", data="{"))


def test_parser_emits_one_complete_event(graph_output: GraphOutput) -> None:
    item = envelope(
        sequence=0,
        event_type="stream.started",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
    )
    parser = SSEParser()
    assert tuple(decode_envelope(raw) for raw in parser.feed(frame(item))) == (item,)
    parser.finish()


def test_validator_accepts_one_monotonic_terminal(
    graph_output: GraphOutput,
) -> None:
    validator = StreamContractValidator()
    for item in (
        envelope(
            sequence=0,
            event_type="stream.started",
            request_id=graph_output.request_id,
            trace_id=graph_output.trace_id,
            session_id=graph_output.session_id,
        ),
        envelope(
            sequence=1,
            event_type="response.completed",
            request_id=graph_output.request_id,
            trace_id=graph_output.trace_id,
            session_id=graph_output.session_id,
            output=graph_output,
        ),
    ):
        validator.accept(item)
    validator.finish()
    assert validator.terminal_event == "response.completed"


def test_validator_rejects_duplicates_decreasing_ids_and_changed_context(
    graph_output: GraphOutput,
) -> None:
    first = envelope(
        sequence=0,
        event_type="stream.started",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
    )
    mutations = (
        first,
        first.model_copy(update={"sequence": 2, "event_id": uuid4()}),
        first.model_copy(update={"sequence": 1, "event_id": uuid4(), "session_id": uuid4()}),
    )
    for invalid in mutations:
        validator = StreamContractValidator()
        validator.accept(first)
        with pytest.raises(SSEProtocolError):
            validator.accept(invalid)


def test_validator_rejects_missing_or_multiple_terminal_events(
    graph_output: GraphOutput,
) -> None:
    started = envelope(
        sequence=0,
        event_type="stream.started",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
    )
    completed = envelope(
        sequence=1,
        event_type="response.completed",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
        output=graph_output,
    )
    validator = StreamContractValidator()
    validator.accept(started)
    with pytest.raises(SSEProtocolError):
        validator.finish()
    validator.accept(completed)
    with pytest.raises(SSEProtocolError):
        validator.accept(completed.model_copy(update={"event_id": uuid4(), "sequence": 2}))


def test_validator_rejects_mismatched_final_output(
    graph_output: GraphOutput,
) -> None:
    invalid_output = graph_output.model_copy(update={"request_id": uuid4()})
    completed = envelope(
        sequence=0,
        event_type="response.completed",
        request_id=graph_output.request_id,
        trace_id=graph_output.trace_id,
        session_id=graph_output.session_id,
        output=invalid_output,
    )
    with pytest.raises(SSEProtocolError):
        StreamContractValidator().accept(completed)
