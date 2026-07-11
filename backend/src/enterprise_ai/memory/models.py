"""Immutable, checkpoint-safe conversational-memory contracts."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from enterprise_ai.memory import MEMORY_SCHEMA_VERSION
from enterprise_ai.models.common import ContractModel, ProcessingStatus
from enterprise_ai.models.graph import Intent, Route
from enterprise_ai.models.identity import AccessLevel, ToolPermission, UserRole
from enterprise_ai.models.retrieval import DocumentType


class SessionOwnership(ContractModel):
    session_id: UUID
    user_id: UUID
    role: UserRole
    permissions: frozenset[ToolPermission]
    policy_fingerprint: Annotated[str, Field(min_length=64, max_length=64)]


class MemoryEvidenceReference(ContractModel):
    evidence_id: UUID
    chunk_id: UUID
    document_id: UUID
    title: Annotated[str, Field(min_length=1, max_length=500)]
    source_file: Annotated[str, Field(min_length=1, max_length=2048)]
    section_path: tuple[Annotated[str, Field(max_length=500)], ...] = ()
    document_type: DocumentType
    department: Annotated[str, Field(min_length=1, max_length=200)]
    access_level: AccessLevel
    version: Annotated[str, Field(min_length=1, max_length=100)]
    updated_date: date
    final_rank: Annotated[int, Field(ge=1)]


class ConversationTurn(ContractModel):
    memory_schema_version: str = MEMORY_SCHEMA_VERSION
    turn_id: UUID
    request_id: UUID
    session_id: UUID
    user_id: UUID
    sequence_number: Annotated[int, Field(ge=1)]
    user_message: Annotated[str, Field(min_length=1, max_length=4_000)]
    assistant_message: Annotated[str, Field(min_length=1, max_length=8_000)]
    intent: Intent
    selected_route: Route
    completion_status: ProcessingStatus
    evidence_references: tuple[MemoryEvidenceReference, ...] = ()
    warnings: tuple[Annotated[str, Field(max_length=500)], ...] = ()
    created_at: datetime


class MemoryContext(ContractModel):
    last_user_question: str | None = None
    last_intent: Intent | None = None
    last_route: Route | None = None
    recent_document_titles: tuple[str, ...] = ()
    recent_document_ids: tuple[UUID, ...] = ()
    recent_incident_ids: tuple[str, ...] = ()
    recent_service_names: tuple[str, ...] = ()
    recent_departments: tuple[str, ...] = ()
    recent_document_types: tuple[DocumentType, ...] = ()
    recent_evidence_ids: tuple[UUID, ...] = ()
    recent_warnings: tuple[str, ...] = ()
    turn_count: Annotated[int, Field(ge=0)] = 0


class ConversationMemorySnapshot(ContractModel):
    memory_schema_version: str = MEMORY_SCHEMA_VERSION
    session_id: UUID
    turn_count: Annotated[int, Field(ge=0)]
    total_characters: Annotated[int, Field(ge=0)]
    evidence_reference_count: Annotated[int, Field(ge=0)]
    turns: tuple[ConversationTurn, ...] = ()
    context: MemoryContext = Field(default_factory=MemoryContext)
    expires_at: datetime


class MemoryUpdate(ContractModel):
    request_id: UUID
    session_id: UUID
    user_id: UUID
    user_message: str
    assistant_message: str
    intent: Intent
    selected_route: Route
    completion_status: ProcessingStatus
    evidence_references: tuple[MemoryEvidenceReference, ...] = ()
    warnings: tuple[str, ...] = ()
    created_at: datetime


class MemoryLoadResult(ContractModel):
    enabled: bool
    found: bool
    snapshot: ConversationMemorySnapshot | None = None


class MemoryEvictionReport(ContractModel):
    evicted_turns: Annotated[int, Field(ge=0)] = 0
    evicted_sessions: Annotated[int, Field(ge=0)] = 0


class MemoryWriteResult(ContractModel):
    stored: bool
    duplicate: bool
    sequence_number: int | None = None
    eviction: MemoryEvictionReport = Field(default_factory=MemoryEvictionReport)


class MemoryStoreStatistics(ContractModel):
    active_sessions: Annotated[int, Field(ge=0)]
    total_turns: Annotated[int, Field(ge=0)]
    expired_sessions_removed: Annotated[int, Field(ge=0)] = 0


class ConversationMemoryInspection(ContractModel):
    memory_schema_version: str = MEMORY_SCHEMA_VERSION
    session_id: UUID
    owner_id: UUID
    turn_count: int
    sequence_numbers: tuple[int, ...]
    character_count: int
    evidence_reference_count: int
    expired: bool
