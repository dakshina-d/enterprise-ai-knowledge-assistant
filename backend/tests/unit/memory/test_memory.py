"""Focused bounded conversational-memory tests."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput
from enterprise_ai.memory.context import build_context, resolve_followup
from enterprise_ai.memory.dependencies import create_memory_service
from enterprise_ai.memory.exceptions import MemoryIntegrityError, MemoryOwnershipError
from enterprise_ai.memory.in_memory import InMemoryConversationStore
from enterprise_ai.memory.models import MemoryUpdate
from enterprise_ai.memory.policies import ownership_for
from enterprise_ai.memory.sanitizer import REDACTED, sanitize_text
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.graph import Intent, Route
from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.hybrid.models import CompletionStatus, HybridRetrievalResult

NOW = datetime(2026, 7, 11, tzinfo=UTC)


class EmptyRetriever:
    async def retrieve(self, *args: object, **kwargs: object) -> HybridRetrievalResult:
        return HybridRetrievalResult(evidence=(), completion_status=CompletionStatus.COMPLETE)


def update(
    session_id: object, user_id: object, message: str, request_id: object | None = None
) -> MemoryUpdate:
    return MemoryUpdate(
        request_id=request_id or uuid4(),
        session_id=session_id,
        user_id=user_id,
        user_message=message,
        assistant_message="Safe response",
        intent=Intent.KNOWLEDGE_LOOKUP,
        selected_route=Route.SIMPLE_RETRIEVAL,
        completion_status=ProcessingStatus.COMPLETED,
        created_at=NOW,
    )


@pytest.mark.parametrize(
    "value",
    [
        "Bearer abc.def.ghi",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature",
        "password=hunter2",
        "-----BEGIN PRIVATE KEY-----secret-----END PRIVATE KEY-----",
        "Authorization: Basic-deadbeef",
    ],
)
def test_sensitive_patterns_are_redacted(value: str) -> None:
    assert REDACTED in sanitize_text(value)
    assert "secret" not in sanitize_text(value).casefold()


def test_safe_identifiers_and_technical_text_are_preserved() -> None:
    value = "INC-PAY-2026-031 HorizonPay Gateway HTTP-504 JDBC 123e4567-e89b-12d3-a456-426614174000"
    assert sanitize_text(value) == value
    assert sanitize_text(value) == sanitize_text(value)


@pytest.mark.asyncio
async def test_create_load_idempotency_and_conflict() -> None:
    settings = RetrievalSettings()
    store = InMemoryConversationStore(settings, clock=lambda: NOW)
    principal = assessment_principal(UserRole.VIEWER)
    session_id = uuid4()
    owner = ownership_for(session_id, principal)
    request_id = uuid4()
    item = update(session_id, principal.identity.user_id, "first", request_id)
    first = await store.upsert_turn(owner, item)
    duplicate = await store.upsert_turn(owner, item)
    snapshot = await store.load(owner)
    assert first.sequence_number == duplicate.sequence_number == 1
    assert duplicate.duplicate
    assert snapshot is not None and snapshot.turn_count == 1
    with pytest.raises(MemoryIntegrityError):
        await store.upsert_turn(
            owner, update(session_id, principal.identity.user_id, "changed", request_id)
        )


@pytest.mark.asyncio
async def test_owner_and_role_changes_fail_closed() -> None:
    store = InMemoryConversationStore(RetrievalSettings(), clock=lambda: NOW)
    viewer = assessment_principal(UserRole.VIEWER)
    analyst = assessment_principal(UserRole.ANALYST)
    session_id = uuid4()
    await store.upsert_turn(
        ownership_for(session_id, viewer),
        update(session_id, viewer.identity.user_id, "viewer"),
    )
    with pytest.raises(MemoryOwnershipError):
        await store.load(ownership_for(session_id, analyst))


@pytest.mark.asyncio
async def test_oldest_first_turn_eviction_and_monotonic_sequence() -> None:
    settings = RetrievalSettings(memory_max_turns_per_session=2)
    store = InMemoryConversationStore(settings, clock=lambda: NOW)
    principal = assessment_principal(UserRole.VIEWER)
    session_id = uuid4()
    owner = ownership_for(session_id, principal)
    for message in ("one", "two", "three"):
        await store.upsert_turn(owner, update(session_id, principal.identity.user_id, message))
    snapshot = await store.load(owner)
    assert snapshot is not None
    assert [turn.user_message for turn in snapshot.turns] == ["two", "three"]
    assert [turn.sequence_number for turn in snapshot.turns] == [2, 3]


@pytest.mark.asyncio
async def test_ttl_expiration_and_cleanup() -> None:
    clock = [NOW]
    settings = RetrievalSettings(memory_session_ttl_seconds=10)
    store = InMemoryConversationStore(settings, clock=lambda: clock[0])
    principal = assessment_principal(UserRole.VIEWER)
    session_id = uuid4()
    owner = ownership_for(session_id, principal)
    await store.upsert_turn(owner, update(session_id, principal.identity.user_id, "one"))
    clock[0] += timedelta(seconds=11)
    assert await store.cleanup_expired() == 1
    assert await store.load(owner) is None


@pytest.mark.asyncio
async def test_concurrent_writes_are_not_lost() -> None:
    store = InMemoryConversationStore(RetrievalSettings(), clock=lambda: NOW)
    principal = assessment_principal(UserRole.VIEWER)
    session_id = uuid4()
    owner = ownership_for(session_id, principal)
    await asyncio.gather(
        *(
            store.upsert_turn(owner, update(session_id, principal.identity.user_id, str(index)))
            for index in range(8)
        )
    )
    snapshot = await store.load(owner)
    assert snapshot is not None
    assert snapshot.turn_count == 8
    assert sorted(turn.sequence_number for turn in snapshot.turns) == list(range(1, 9))


def test_context_and_followup_resolution_are_deterministic() -> None:
    context = build_context((), maximum_topics=5, maximum_identifiers=5)
    query, detected, used = resolve_followup("Explain that runbook", context)
    assert query == "Explain that runbook"
    assert detected and not used


@pytest.mark.asyncio
async def test_graph_memory_survives_invocations_and_is_idempotent(tmp_path: object) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"build_fingerprint":"' + "a" * 64 + '"}', encoding="utf-8")
    settings = RetrievalSettings(ingestion_manifest_path=manifest)
    memory = create_memory_service(settings)
    graph = build_graph(
        settings,
        EmptyRetriever(),
        checkpointer=create_checkpointer(),
        memory=memory,
    )
    runtime = GraphRuntime(graph, settings, memory)
    principal = assessment_principal(UserRole.VIEWER)
    session_id = uuid4()
    first = GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=session_id,
        principal=principal,
        user_message="hello",
    )
    first_output = await runtime.ainvoke(first)
    second = first.model_copy(
        update={"request_id": uuid4(), "trace_id": uuid4(), "user_message": "explain that again"}
    )
    second_output = await runtime.ainvoke(second)
    duplicate = await runtime.ainvoke(second)
    inspection = await runtime.inspect_memory(second)
    assert not first_output.memory_used
    assert second_output.memory_used and second_output.context_resolved
    assert duplicate.memory_update_status == "duplicate"
    assert inspection.turn_count == 2
