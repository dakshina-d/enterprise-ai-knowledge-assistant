"""Replaceable asynchronous conversation-memory store boundary."""

from typing import Protocol
from uuid import UUID

from enterprise_ai.memory.models import (
    ConversationMemoryInspection,
    ConversationMemorySnapshot,
    MemoryStoreStatistics,
    MemoryUpdate,
    MemoryWriteResult,
    SessionOwnership,
)


class ConversationMemoryStore(Protocol):
    async def load(self, ownership: SessionOwnership) -> ConversationMemorySnapshot | None: ...

    async def upsert_turn(
        self, ownership: SessionOwnership, update: MemoryUpdate
    ) -> MemoryWriteResult: ...

    async def delete(self, ownership: SessionOwnership) -> bool: ...

    async def cleanup_expired(self, *, maximum: int = 100) -> int: ...

    async def statistics(self) -> MemoryStoreStatistics: ...

    async def inspect(self, ownership: SessionOwnership) -> ConversationMemoryInspection | None: ...

    async def owns(self, session_id: UUID, ownership: SessionOwnership) -> bool: ...
