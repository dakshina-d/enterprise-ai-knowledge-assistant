"""Explicit memory construction without global singleton state."""

from enterprise_ai.memory.in_memory import InMemoryConversationStore
from enterprise_ai.memory.service import ConversationMemoryService
from enterprise_ai.retrieval.config import RetrievalSettings


def create_memory_service(settings: RetrievalSettings) -> ConversationMemoryService:
    return ConversationMemoryService(InMemoryConversationStore(settings), settings)
