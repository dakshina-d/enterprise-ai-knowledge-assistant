"""Public chat, session, citation, and answer contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator

from enterprise_ai.models.common import (
    ChunkId,
    ContractModel,
    DocumentId,
    EvidenceId,
    MessageId,
    ProcessingStatus,
    RequestId,
    SessionId,
    TimestampedModel,
    TraceId,
    UserId,
    new_identifier,
)
from enterprise_ai.models.validation import ensure_utc_aware, validate_text_length

MAX_MESSAGE_LENGTH = 16_000


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class CitationReference(ContractModel):
    evidence_id: EvidenceId
    document_id: DocumentId
    chunk_id: ChunkId
    title: Annotated[str, Field(min_length=1, max_length=500)]
    source: Annotated[str, Field(min_length=1, max_length=2048)]
    section: Annotated[str | None, Field(max_length=500)] = None


class ChatMessage(TimestampedModel):
    message_id: MessageId = Field(default_factory=new_identifier)
    role: ChatRole
    content: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)]
    citations: tuple[CitationReference, ...] = ()

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return validate_text_length(value, maximum=MAX_MESSAGE_LENGTH)


class ChatSessionSummary(TimestampedModel):
    session_id: SessionId = Field(default_factory=new_identifier)
    user_id: UserId
    title: Annotated[str, Field(min_length=1, max_length=200)]
    updated_at: datetime
    status: ProcessingStatus = ProcessingStatus.ACCEPTED

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return validate_text_length(value, maximum=200)

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: datetime) -> datetime:
        return ensure_utc_aware(value)


class CreateChatSessionRequest(ContractModel):
    title: Annotated[str | None, Field(max_length=200)] = None

    @field_validator("title")
    @classmethod
    def validate_optional_title(cls, value: str | None) -> str | None:
        return None if value is None else validate_text_length(value, maximum=200)


class CreateChatSessionResponse(ContractModel):
    session: ChatSessionSummary


class SendMessageRequest(ContractModel):
    content: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)]
    client_message_id: MessageId = Field(default_factory=new_identifier)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return validate_text_length(value, maximum=MAX_MESSAGE_LENGTH)


class SendMessageAcceptedResponse(ContractModel):
    request_id: RequestId
    message_id: MessageId
    session_id: SessionId
    status: ProcessingStatus = ProcessingStatus.ACCEPTED
    events_url: Annotated[str, Field(pattern=r"^/api/v1/chat/sessions/")]


class ConversationContextSummary(ContractModel):
    summary: Annotated[str, Field(min_length=1, max_length=8_000)]
    message_count: Annotated[int, Field(ge=0)]
    last_message_at: datetime | None = None

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return validate_text_length(value, maximum=8_000)

    @field_validator("last_message_at")
    @classmethod
    def validate_last_message_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc_aware(value)


class FinalAnswer(ContractModel):
    answer: Annotated[str, Field(min_length=1, max_length=32_000)]
    citations: tuple[CitationReference, ...] = ()
    warnings: tuple[Annotated[str, Field(max_length=500)], ...] = ()
    completion_status: ProcessingStatus
    trace_id: TraceId

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value: str) -> str:
        return validate_text_length(value, maximum=32_000)


class ChatSessionResponse(ContractModel):
    session: ChatSessionSummary
    messages: tuple[ChatMessage, ...]
    context_summary: ConversationContextSummary | None = None
