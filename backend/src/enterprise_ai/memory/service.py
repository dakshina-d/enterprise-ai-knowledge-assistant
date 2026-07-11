"""Graph-facing conversational-memory application service."""

from datetime import datetime
from uuid import UUID

from enterprise_ai.memory.models import (
    ConversationMemoryInspection,
    MemoryEvidenceReference,
    MemoryLoadResult,
    MemoryUpdate,
    MemoryWriteResult,
)
from enterprise_ai.memory.policies import ownership_for
from enterprise_ai.memory.sanitizer import sanitize_text
from enterprise_ai.memory.store import ConversationMemoryStore
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.graph import Intent, Route
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.security.authorization import AuthorizationService


class ConversationMemoryService:
    def __init__(self, store: ConversationMemoryStore, settings: RetrievalSettings) -> None:
        self.store = store
        self.settings = settings
        self.authorization = AuthorizationService()

    async def load(self, session_id: UUID, principal: AuthenticatedPrincipal) -> MemoryLoadResult:
        if not self.settings.memory_enabled:
            return MemoryLoadResult(enabled=False, found=False)
        snapshot = await self.store.load(ownership_for(session_id, principal))
        return MemoryLoadResult(enabled=True, found=snapshot is not None, snapshot=snapshot)

    def evidence_references(
        self, evidence: tuple[HybridEvidence, ...], principal: AuthenticatedPrincipal
    ) -> tuple[MemoryEvidenceReference, ...]:
        allowed = principal.identity.role
        allowed_levels = self.authorization.allowed_access_levels(principal)
        result: list[MemoryEvidenceReference] = []
        seen: set[UUID] = set()
        for item in evidence:
            source = item.evidence
            if (
                source.chunk_id in seen
                or allowed not in source.allowed_roles
                or source.access_level not in allowed_levels
            ):
                continue
            seen.add(source.chunk_id)
            result.append(
                MemoryEvidenceReference(
                    evidence_id=source.evidence_id,
                    chunk_id=source.chunk_id,
                    document_id=source.document_id,
                    title=source.title,
                    source_file=source.source_file,
                    section_path=source.section_path,
                    document_type=source.document_type,
                    department=source.department,
                    access_level=source.access_level,
                    version=source.version,
                    updated_date=source.updated_date,
                    final_rank=item.final_rank,
                )
            )
        return tuple(result[: self.settings.memory_max_evidence_references])

    async def update(
        self,
        *,
        request_id: UUID,
        session_id: UUID,
        principal: AuthenticatedPrincipal,
        user_message: str,
        assistant_message: str,
        intent: Intent,
        selected_route: Route,
        completion_status: ProcessingStatus,
        evidence: tuple[HybridEvidence, ...],
        warnings: tuple[str, ...],
        created_at: datetime,
    ) -> MemoryWriteResult:
        if not self.settings.memory_enabled or completion_status is ProcessingStatus.FAILED:
            return MemoryWriteResult(stored=False, duplicate=False)
        sanitized_user = sanitize_text(
            user_message,
            enabled=self.settings.memory_redact_sensitive_patterns,
        )[: self.settings.memory_max_user_message_characters]
        sanitized_assistant = sanitize_text(
            assistant_message,
            enabled=self.settings.memory_redact_sensitive_patterns,
        )[: self.settings.memory_max_assistant_message_characters]
        references = (
            ()
            if completion_status is ProcessingStatus.DENIED
            else self.evidence_references(evidence, principal)
        )
        update = MemoryUpdate(
            request_id=request_id,
            session_id=session_id,
            user_id=principal.identity.user_id,
            user_message=sanitized_user,
            assistant_message=sanitized_assistant,
            intent=intent,
            selected_route=selected_route,
            completion_status=completion_status,
            evidence_references=references,
            warnings=tuple(dict.fromkeys(warnings))[: self.settings.graph_max_warnings],
            created_at=created_at,
        )
        return await self.store.upsert_turn(ownership_for(session_id, principal), update)

    async def inspect(
        self, session_id: UUID, principal: AuthenticatedPrincipal
    ) -> ConversationMemoryInspection | None:
        return await self.store.inspect(ownership_for(session_id, principal))
