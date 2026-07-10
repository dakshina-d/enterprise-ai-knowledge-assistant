"""Unit tests for shared domain and boundary contracts."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from enterprise_ai.models.chat import (
    ChatMessage,
    ChatRole,
    CitationReference,
    FinalAnswer,
    SendMessageRequest,
)
from enterprise_ai.models.common import PaginationMetadata, PaginationRequest, ProcessingStatus
from enterprise_ai.models.errors import (
    ApplicationErrorResponse,
    ErrorCategory,
    ErrorCode,
    ErrorSeverity,
    InternalErrorContext,
)
from enterprise_ai.models.events import (
    EVENT_VERSION,
    AgentEvent,
    AgentEventStatus,
    AgentEventType,
    PublicAgentEventPayload,
)
from enterprise_ai.models.feedback import AnswerFeedbackRequest, FeedbackRating
from enterprise_ai.models.graph import GraphStateSnapshot, PublicAgentStatus
from enterprise_ai.models.identity import (
    AccessLevel,
    AuthenticatedPrincipal,
    LoginRequest,
    LoginResponse,
    PublicUserProfile,
    ToolPermission,
    UserRole,
)
from enterprise_ai.models.retrieval import (
    DocumentMetadata,
    DocumentType,
    EvidenceItem,
    IndexedChunk,
    MetadataFilters,
)
from enterprise_ai.models.tools import (
    ToolAuthorizationDecision,
    ToolError,
    ToolName,
    ToolRequest,
)
from enterprise_ai.models.validation import ensure_utc_aware, validate_json_compatible
from pydantic import SecretStr, ValidationError


def test_identity_roles_and_password_masking() -> None:
    request = LoginRequest(username="demo-user", password=SecretStr("correct-horse-battery"))

    assert "correct-horse-battery" not in repr(request)
    assert "correct-horse-battery" not in request.model_dump_json()
    assert request.password.get_secret_value() == "correct-horse-battery"
    assert UserRole.VIEWER.value == "viewer"

    with pytest.raises(ValidationError):
        PublicUserProfile(user_id=uuid4(), username="demo", display_name="Demo", role="superuser")


def test_public_identity_response_has_no_password_field() -> None:
    profile = PublicUserProfile(
        user_id=uuid4(), username="demo", display_name="Demo User", role=UserRole.ANALYST
    )
    response = LoginResponse(
        access_token="test-access-token",
        expires_in=3600,
        user=profile,
        permissions=frozenset(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    assert "password" not in response.model_dump_json()


def test_principal_expiry_and_access_level_hierarchy_are_validated() -> None:
    now = datetime.now(UTC)
    identity = PublicUserProfile(
        user_id=uuid4(), username="demo", display_name="Demo", role=UserRole.VIEWER
    )
    principal = AuthenticatedPrincipal(
        identity=identity,
        authenticated_at=now,
        expires_at=now + timedelta(hours=1),
    )

    assert principal.expires_at > principal.authenticated_at
    assert AccessLevel.RESTRICTED.rank > AccessLevel.INTERNAL.rank
    assert AccessLevel.CONFIDENTIAL.value == "confidential"
    with pytest.raises(ValidationError):
        AuthenticatedPrincipal(identity=identity, authenticated_at=now, expires_at=now)


@pytest.mark.parametrize("content", ["", "   ", "\n\t"])
def test_blank_chat_messages_are_rejected(content: str) -> None:
    with pytest.raises(ValidationError):
        SendMessageRequest(content=content)


def test_excessively_long_chat_message_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SendMessageRequest(content="x" * 16_001)


def test_chat_message_and_typed_final_answer_serialize() -> None:
    document_id = uuid4()
    chunk_id = uuid4()
    citation = CitationReference(
        evidence_id=uuid4(),
        document_id=document_id,
        chunk_id=chunk_id,
        title="Security Policy",
        source="mock://security-policy",
        section="Access",
    )
    message = ChatMessage(role=ChatRole.ASSISTANT, content="Grounded answer", citations=(citation,))
    answer = FinalAnswer(
        answer="Grounded answer",
        citations=(citation,),
        completion_status=ProcessingStatus.COMPLETED,
        trace_id=uuid4(),
    )

    assert message.model_dump(mode="json")["role"] == "assistant"
    assert answer.citations[0].document_id == document_id
    assert answer.model_dump(mode="json")["completion_status"] == "completed"


def _document_metadata() -> DocumentMetadata:
    return DocumentMetadata(
        document_id=uuid4(),
        title="Architecture Guide",
        source="mock://architecture-guide",
        department="Engineering",
        document_type=DocumentType.ARCHITECTURE,
        access_level=AccessLevel.INTERNAL,
        allowed_roles=frozenset({UserRole.VIEWER, UserRole.ANALYST}),
        created_date=date(2026, 1, 1),
        updated_date=date(2026, 2, 1),
        version="1.0",
        content_hash="a" * 64,
    )


def test_document_metadata_and_evidence_preserve_attribution() -> None:
    metadata = _document_metadata()
    chunk_id = uuid4()
    chunk = IndexedChunk(
        chunk_id=chunk_id,
        document_id=metadata.document_id,
        section="Overview",
        chunk_index=0,
        text="Architecture evidence",
        metadata=metadata,
        dense_score=0.8,
        sparse_score=2.4,
        hybrid_score=0.9,
    )
    evidence = EvidenceItem(
        document_id=metadata.document_id,
        chunk_id=chunk_id,
        title=metadata.title,
        source=metadata.source,
        section=chunk.section,
        version=metadata.version,
        content_hash=metadata.content_hash,
        text=chunk.text,
        score=0.9,
    )

    assert evidence.document_id == metadata.document_id
    assert evidence.chunk_id == chunk_id
    assert evidence.content_hash == metadata.content_hash


def test_retrieval_rejects_invalid_scores_dates_and_document_types() -> None:
    metadata = _document_metadata()
    with pytest.raises(ValidationError):
        IndexedChunk(
            chunk_id=uuid4(),
            document_id=metadata.document_id,
            chunk_index=0,
            text="Evidence",
            metadata=metadata,
            hybrid_score=1.1,
        )
    with pytest.raises(ValidationError):
        MetadataFilters(created_from=date(2026, 2, 1), created_to=date(2026, 1, 1))
    invalid = metadata.model_dump()
    invalid["document_type"] = "spreadsheet"
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate(invalid)


def test_tool_request_accepts_bounded_json_parameters() -> None:
    request = ToolRequest(
        request_id=uuid4(),
        tool_name=ToolName.KNOWLEDGE_SEARCH,
        parameters={"query": "availability", "filters": {"department": ["Engineering"]}},
    )
    decision = ToolAuthorizationDecision(
        tool_call_id=request.tool_call_id,
        allowed=True,
        reason_code="policy.allowed",
        public_explanation="The tool is permitted for this request.",
        required_permission=ToolPermission.KNOWLEDGE_SEARCH,
    )

    assert request.parameters["query"] == "availability"
    assert decision.model_dump(mode="json")["allowed"] is True


def test_tool_request_rejects_deep_oversized_and_unsupported_parameters() -> None:
    deep: object = "leaf"
    for _ in range(7):
        deep = {"level": deep}
    with pytest.raises(ValidationError):
        ToolRequest(request_id=uuid4(), tool_name=ToolName.EMPLOYEE_DIRECTORY, parameters=deep)
    with pytest.raises(ValidationError):
        ToolRequest(
            request_id=uuid4(),
            tool_name=ToolName.PYTHON_ANALYSIS,
            parameters={"data": "x" * 20_000},
        )
    with pytest.raises(ValidationError):
        ToolRequest(
            request_id=uuid4(),
            tool_name=ToolName.PYTHON_ANALYSIS,
            parameters={"secret": SecretStr("do-not-serialize")},
        )


def test_tool_error_is_sanitized_and_requires_no_exception() -> None:
    error = ToolError(
        tool_call_id=uuid4(),
        tool_name=ToolName.PYTHON_ANALYSIS,
        code="tool.execution_failed",
        safe_message="Analysis could not be completed.",
    )
    assert "exception" not in error.model_dump()


def _event(**overrides: object) -> AgentEvent:
    values: dict[str, object] = {
        "event_type": AgentEventType.RESPONSE_TOKEN,
        "sequence_number": 0,
        "request_id": uuid4(),
        "session_id": uuid4(),
        "trace_id": uuid4(),
        "status": AgentEventStatus.RUNNING,
        "public_message": "Generating response",
        "payload": PublicAgentEventPayload(token="Hello"),
    }
    values.update(overrides)
    return AgentEvent.model_validate(values)


def test_event_generates_identifiers_timestamp_and_safe_serialization() -> None:
    event = _event()
    serialized = event.to_public_dict()

    assert event.event_id
    assert event.timestamp.tzinfo is not None
    assert event.event_version == EVENT_VERSION
    assert serialized["event_type"] == "response.token"
    assert "diagnostic_context" not in serialized


def test_event_rejects_negative_sequence_unsupported_type_and_private_payload() -> None:
    with pytest.raises(ValidationError):
        _event(sequence_number=-1)
    with pytest.raises(ValidationError):
        _event(event_type="response.private_reasoning")
    with pytest.raises(ValidationError):
        PublicAgentEventPayload.model_validate({"raw_prompt": "private"})
    with pytest.raises(ValidationError):
        PublicAgentEventPayload.model_validate({"token": object()})


def test_public_error_excludes_internal_diagnostics_and_validates_retry_metadata() -> None:
    request_id = uuid4()
    public = ApplicationErrorResponse(
        category=ErrorCategory.RATE_LIMIT,
        code=ErrorCode.RATE_LIMIT_EXCEEDED,
        message="Try again later.",
        request_id=request_id,
        retryable=True,
        retry_after_seconds=30,
    )
    internal = InternalErrorContext(
        category=ErrorCategory.INTERNAL,
        code=ErrorCode.INTERNAL_ERROR,
        severity=ErrorSeverity.ERROR,
        request_id=request_id,
        operation="process_message",
        diagnostic_message="Sanitized internal diagnostic",
    )

    assert "diagnostic_message" not in public.model_dump_json()
    assert "diagnostic_message" in internal.model_dump_json()
    with pytest.raises(ValidationError):
        ApplicationErrorResponse(
            category=ErrorCategory.RATE_LIMIT,
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            message="Try later.",
            request_id=request_id,
            retryable=True,
            retry_after_seconds=0,
        )


def test_graph_state_enforces_recursion_and_non_negative_budgets() -> None:
    base = {
        "request_id": uuid4(),
        "trace_id": uuid4(),
        "session_id": uuid4(),
        "user_id": uuid4(),
        "user_role": UserRole.VIEWER,
    }
    with pytest.raises(ValidationError):
        GraphStateSnapshot(**base, recursion_depth=3, maximum_recursion_depth=2)
    with pytest.raises(ValidationError):
        GraphStateSnapshot(**base, remaining_task_budget=-1)
    with pytest.raises(ValidationError):
        GraphStateSnapshot(**base, remaining_time_budget_seconds=-0.1)


def test_public_agent_status_has_no_private_reasoning_fields() -> None:
    status = PublicAgentStatus(
        request_id=uuid4(),
        status=ProcessingStatus.RUNNING,
        node="simple_retrieval",
        public_message="Searching approved knowledge",
    )
    assert "reasoning" not in status.model_dump_json()
    with pytest.raises(ValidationError):
        PublicAgentStatus.model_validate({**status.model_dump(), "chain_of_thought": "private"})


def test_feedback_and_pagination_contracts_are_bounded() -> None:
    feedback = AnswerFeedbackRequest(
        session_id=uuid4(),
        message_id=uuid4(),
        request_id=uuid4(),
        trace_id=uuid4(),
        rating=FeedbackRating.POSITIVE,
        reason="helpful",
        comment="The citations were useful.",
    )
    page = PaginationRequest(limit=25, cursor="next-page")
    metadata = PaginationMetadata(limit=25, returned=10, next_cursor=None)

    assert feedback.model_dump(mode="json")["rating"] == "positive"
    assert page.limit == 25
    assert metadata.returned == 10
    with pytest.raises(ValidationError):
        PaginationMetadata(limit=10, returned=11)


def test_validation_helpers_reject_depth_size_naive_datetime_and_objects() -> None:
    deep: object = "leaf"
    for _ in range(4):
        deep = [deep]
    with pytest.raises(ValueError, match="maximum depth"):
        validate_json_compatible(deep, maximum_depth=2)
    with pytest.raises(ValueError, match="exceeds"):
        validate_json_compatible({"value": "x" * 100}, maximum_bytes=20)
    with pytest.raises(ValueError, match="timezone"):
        ensure_utc_aware(datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="unsupported"):
        validate_json_compatible({"value": object()})
