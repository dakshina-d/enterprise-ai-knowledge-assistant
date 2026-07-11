"""Concurrency-safe bounded process-local memory store."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from enterprise_ai.memory.context import build_context
from enterprise_ai.memory.exceptions import (
    MemoryCapacityError,
    MemoryIntegrityError,
    MemoryOwnershipError,
)
from enterprise_ai.memory.models import (
    ConversationMemoryInspection,
    ConversationMemorySnapshot,
    ConversationTurn,
    MemoryEvictionReport,
    MemoryStoreStatistics,
    MemoryUpdate,
    MemoryWriteResult,
    SessionOwnership,
)
from enterprise_ai.retrieval.config import RetrievalSettings


@dataclass
class _Session:
    ownership: SessionOwnership
    turns: tuple[ConversationTurn, ...]
    next_sequence: int
    expires_at: datetime
    last_accessed: datetime


class InMemoryConversationStore:
    def __init__(
        self,
        settings: RetrievalSettings,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sessions: dict[UUID, _Session] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._catalog_lock = asyncio.Lock()
        self._expired_removed = 0

    def _assert_owner(self, session: _Session, ownership: SessionOwnership) -> None:
        if session.ownership != ownership:
            raise MemoryOwnershipError("session memory is owned by another principal")

    async def _lock_for(self, session_id: UUID) -> asyncio.Lock:
        async with self._catalog_lock:
            return self._locks.setdefault(session_id, asyncio.Lock())

    def _snapshot(self, session: _Session) -> ConversationMemorySnapshot:
        turns = tuple(session.turns)
        references = sum(len(turn.evidence_references) for turn in turns)
        characters = sum(len(turn.user_message) + len(turn.assistant_message) for turn in turns)
        return ConversationMemorySnapshot(
            session_id=session.ownership.session_id,
            turn_count=len(turns),
            total_characters=characters,
            evidence_reference_count=references,
            turns=turns,
            context=build_context(
                turns,
                maximum_topics=self._settings.memory_max_context_topics,
                maximum_identifiers=self._settings.memory_max_context_identifiers,
            ),
            expires_at=session.expires_at,
        )

    async def load(self, ownership: SessionOwnership) -> ConversationMemorySnapshot | None:
        lock = await self._lock_for(ownership.session_id)
        async with lock:
            session = self._sessions.get(ownership.session_id)
            if session is None:
                return None
            self._assert_owner(session, ownership)
            now = self._clock()
            if session.expires_at <= now:
                del self._sessions[ownership.session_id]
                self._expired_removed += 1
                return None
            session.last_accessed = now
            return self._snapshot(session)

    async def upsert_turn(
        self, ownership: SessionOwnership, update: MemoryUpdate
    ) -> MemoryWriteResult:
        if update.session_id != ownership.session_id or update.user_id != ownership.user_id:
            raise MemoryOwnershipError("memory update identity does not match session ownership")
        lock = await self._lock_for(ownership.session_id)
        async with lock:
            now = self._clock()
            session = self._sessions.get(ownership.session_id)
            if session is not None and session.expires_at <= now:
                del self._sessions[ownership.session_id]
                session = None
                self._expired_removed += 1
            if session is None:
                await self._make_capacity(now)
                session = _Session(
                    ownership=ownership,
                    turns=(),
                    next_sequence=1,
                    expires_at=now + timedelta(seconds=self._settings.memory_session_ttl_seconds),
                    last_accessed=now,
                )
                self._sessions[ownership.session_id] = session
            self._assert_owner(session, ownership)
            existing = next(
                (turn for turn in session.turns if turn.request_id == update.request_id), None
            )
            if existing is not None:
                candidate = self._turn(update, existing.sequence_number)
                if existing != candidate:
                    raise MemoryIntegrityError("request ID already has different memory content")
                return MemoryWriteResult(
                    stored=False, duplicate=True, sequence_number=existing.sequence_number
                )
            turn = self._turn(update, session.next_sequence)
            if (
                len(turn.user_message) + len(turn.assistant_message)
                > self._settings.memory_max_total_characters
            ):
                raise MemoryCapacityError("turn exceeds the configured memory capacity")
            session.turns = (*session.turns, turn)
            session.next_sequence += 1
            session.last_accessed = now
            session.expires_at = now + timedelta(seconds=self._settings.memory_session_ttl_seconds)
            evicted = self._evict_turns(session)
            return MemoryWriteResult(
                stored=True,
                duplicate=False,
                sequence_number=turn.sequence_number,
                eviction=MemoryEvictionReport(evicted_turns=evicted),
            )

    def _turn(self, update: MemoryUpdate, sequence: int) -> ConversationTurn:
        return ConversationTurn(
            turn_id=uuid5(NAMESPACE_URL, f"memory:{update.session_id}:{update.request_id}"),
            sequence_number=sequence,
            **update.model_dump(),
        )

    def _evict_turns(self, session: _Session) -> int:
        evicted = 0
        while session.turns:
            snapshot = self._snapshot(session)
            if (
                snapshot.turn_count <= self._settings.memory_max_turns_per_session
                and snapshot.total_characters <= self._settings.memory_max_total_characters
                and snapshot.evidence_reference_count
                <= self._settings.memory_max_evidence_references
            ):
                break
            session.turns = session.turns[1:]
            evicted += 1
        return evicted

    async def _make_capacity(self, now: datetime) -> None:
        expired = [key for key, session in self._sessions.items() if session.expires_at <= now][
            :100
        ]
        for key in expired:
            self._sessions.pop(key, None)
            self._expired_removed += 1
        if len(self._sessions) >= self._settings.memory_max_sessions:
            oldest = min(self._sessions.items(), key=lambda item: item[1].last_accessed)[0]
            self._sessions.pop(oldest, None)

    async def delete(self, ownership: SessionOwnership) -> bool:
        lock = await self._lock_for(ownership.session_id)
        async with lock:
            session = self._sessions.get(ownership.session_id)
            if session is None:
                return False
            self._assert_owner(session, ownership)
            del self._sessions[ownership.session_id]
            return True

    async def cleanup_expired(self, *, maximum: int = 100) -> int:
        now = self._clock()
        async with self._catalog_lock:
            expired = [key for key, session in self._sessions.items() if session.expires_at <= now][
                :maximum
            ]
            for key in expired:
                self._sessions.pop(key, None)
            self._expired_removed += len(expired)
            return len(expired)

    async def statistics(self) -> MemoryStoreStatistics:
        async with self._catalog_lock:
            return MemoryStoreStatistics(
                active_sessions=len(self._sessions),
                total_turns=sum(len(session.turns) for session in self._sessions.values()),
                expired_sessions_removed=self._expired_removed,
            )

    async def inspect(self, ownership: SessionOwnership) -> ConversationMemoryInspection | None:
        snapshot = await self.load(ownership)
        if snapshot is None:
            return None
        return ConversationMemoryInspection(
            session_id=ownership.session_id,
            owner_id=ownership.user_id,
            turn_count=snapshot.turn_count,
            sequence_numbers=tuple(turn.sequence_number for turn in snapshot.turns),
            character_count=snapshot.total_characters,
            evidence_reference_count=snapshot.evidence_reference_count,
            expired=False,
        )

    async def owns(self, session_id: UUID, ownership: SessionOwnership) -> bool:
        lock = await self._lock_for(session_id)
        async with lock:
            session = self._sessions.get(session_id)
            return session is None or session.ownership == ownership
