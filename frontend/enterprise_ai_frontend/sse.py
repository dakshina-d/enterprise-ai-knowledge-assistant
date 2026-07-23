"""Small bounded standards-aware SSE parser and stream contract validator."""

import codecs
import json
from dataclasses import dataclass
from uuid import UUID

from enterprise_ai.api.schemas import ChatStreamEnvelope
from pydantic import ValidationError

from frontend.enterprise_ai_frontend.errors import SSEProtocolError

DEFAULT_MAX_EVENT_BYTES = 256_000
TERMINAL_EVENTS = frozenset({"response.completed", "response.failed", "stream.error"})


@dataclass(frozen=True)
class RawSSEEvent:
    event: str
    event_id: str
    data: str


class SSEParser:
    def __init__(self, *, maximum_event_bytes: int = DEFAULT_MAX_EVENT_BYTES) -> None:
        if maximum_event_bytes < 1_024:
            raise ValueError("maximum SSE event size is too small")
        self._maximum_event_bytes = maximum_event_bytes
        self._decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self._buffer = ""
        self._event = ""
        self._event_id = ""
        self._data: list[str] = []
        self._frame_size = 0

    def feed(self, chunk: bytes) -> tuple[RawSSEEvent, ...]:
        try:
            self._buffer += self._decoder.decode(chunk)
        except UnicodeDecodeError as error:
            raise SSEProtocolError("The activity stream was not valid UTF-8.") from error
        events: list[RawSSEEvent] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.endswith("\r"):
                line = line[:-1]
            item = self._line(line)
            if item is not None:
                events.append(item)
        if self._frame_size + len(self._buffer.encode("utf-8")) > self._maximum_event_bytes:
            raise SSEProtocolError("An activity event exceeded the safe size limit.")
        return tuple(events)

    def finish(self) -> None:
        try:
            self._buffer += self._decoder.decode(b"", final=True)
        except UnicodeDecodeError as error:
            raise SSEProtocolError("The activity stream ended with invalid UTF-8.") from error
        if self._buffer or self._event or self._event_id or self._data:
            raise SSEProtocolError("The activity stream ended with an incomplete event.")

    def _line(self, line: str) -> RawSSEEvent | None:
        self._frame_size += len(line.encode("utf-8")) + 1
        if self._frame_size > self._maximum_event_bytes:
            raise SSEProtocolError("An activity event exceeded the safe size limit.")
        if line == "":
            if not (self._event or self._event_id or self._data):
                self._frame_size = 0
                return None
            item = RawSSEEvent(
                event=self._event or "message",
                event_id=self._event_id,
                data="\n".join(self._data),
            )
            self._event = ""
            self._event_id = ""
            self._data = []
            self._frame_size = 0
            return item
        if line.startswith(":"):
            return None
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event = value
        elif field == "id":
            if "\x00" in value:
                raise SSEProtocolError()
            self._event_id = value
        elif field == "data":
            self._data.append(value)
        return None


def decode_envelope(event: RawSSEEvent) -> ChatStreamEnvelope:
    try:
        payload = json.loads(event.data)
        envelope = ChatStreamEnvelope.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        raise SSEProtocolError() from error
    if event.event != envelope.event_type or event.event_id != str(envelope.event_id):
        raise SSEProtocolError()
    return envelope


class StreamContractValidator:
    def __init__(self) -> None:
        self._expected_sequence = 0
        self._event_ids: set[UUID] = set()
        self._request_id: UUID | None = None
        self._trace_id: UUID | None = None
        self._session_id: UUID | None = None
        self._terminal_event: str | None = None

    def accept(self, envelope: ChatStreamEnvelope) -> None:
        if self._terminal_event is not None:
            raise SSEProtocolError("The activity stream continued after completion.")
        if envelope.sequence != self._expected_sequence or envelope.event_id in self._event_ids:
            raise SSEProtocolError()
        self._expected_sequence += 1
        self._event_ids.add(envelope.event_id)
        if self._request_id is None:
            self._request_id = envelope.request_id
            self._trace_id = envelope.trace_id
            self._session_id = envelope.session_id
        elif (
            envelope.request_id != self._request_id
            or envelope.trace_id != self._trace_id
            or envelope.session_id != self._session_id
        ):
            raise SSEProtocolError()
        event = envelope.agent_event
        if event is not None and (
            event.event_type.value != envelope.event_type
            or event.request_id != envelope.request_id
            or event.trace_id != envelope.trace_id
            or event.session_id != envelope.session_id
        ):
            raise SSEProtocolError()
        response = envelope.response
        if response is not None and (
            response.request_id != envelope.request_id
            or response.trace_id != envelope.trace_id
            or response.session_id != envelope.session_id
        ):
            raise SSEProtocolError()
        if envelope.event_type in TERMINAL_EVENTS:
            self._terminal_event = envelope.event_type
            if envelope.event_type == "response.completed" and response is None:
                raise SSEProtocolError("The completed stream did not contain a final response.")
            if envelope.event_type == "stream.error" and envelope.error is None:
                raise SSEProtocolError()

    def finish(self) -> None:
        if self._terminal_event is None:
            raise SSEProtocolError("The activity stream ended before a final event.")

    @property
    def terminal_event(self) -> str | None:
        return self._terminal_event
