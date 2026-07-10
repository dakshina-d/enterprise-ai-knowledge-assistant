"""Public answer-feedback contracts without persistence behavior."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator

from enterprise_ai.models.common import (
    ContractModel,
    FeedbackId,
    MessageId,
    RequestId,
    SessionId,
    TraceId,
    new_identifier,
)
from enterprise_ai.models.validation import validate_text_length


class FeedbackRating(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class AnswerFeedbackRequest(ContractModel):
    session_id: SessionId
    message_id: MessageId
    request_id: RequestId
    trace_id: TraceId
    rating: FeedbackRating
    reason: Annotated[str | None, Field(max_length=100)] = None
    comment: Annotated[str | None, Field(max_length=2_000)] = None

    @field_validator("reason", "comment")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else validate_text_length(value, maximum=2_000)


class AnswerFeedbackResponse(ContractModel):
    feedback_id: FeedbackId = Field(default_factory=new_identifier)
    status: Annotated[str, Field(pattern="^recorded$")] = "recorded"
