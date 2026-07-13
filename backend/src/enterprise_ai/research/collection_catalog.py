"""Authorization-filtered, metadata-only collection exploration."""

from enterprise_ai_ingestion.models import ChunkRecord

from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.models.retrieval import DocumentMetadata
from enterprise_ai.research.models import CollectionCatalog
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.indexer import load_current_chunks
from enterprise_ai.security.authorization import AuthorizationService


class CollectionCatalogService:
    def __init__(self, settings: RetrievalSettings, authorization: AuthorizationService) -> None:
        self.settings = settings
        self.authorization = authorization

    def build(self, principal: AuthenticatedPrincipal) -> CollectionCatalog:
        manifest, chunks = load_current_chunks(self.settings)
        documents: dict[object, ChunkRecord] = {}
        for chunk in chunks:
            metadata = DocumentMetadata(
                document_id=chunk.document_id,
                title=chunk.title,
                source=chunk.source,
                department=chunk.department,
                document_type=chunk.document_type,
                access_level=chunk.access_level,
                allowed_roles=frozenset(chunk.allowed_roles),
                created_date=chunk.created_date,
                updated_date=chunk.updated_date,
                version=chunk.version,
                content_hash=chunk.chunk_content_hash,
            )
            if self.authorization.is_document_authorized(principal, metadata):
                documents.setdefault(chunk.document_id, chunk)
        values = tuple(documents.values())
        dates = sorted({item.updated_date for item in values})
        return CollectionCatalog(
            build_fingerprint=manifest.build_fingerprint,
            document_count=len(values),
            departments=tuple(sorted({item.department for item in values})),
            document_types=tuple(sorted({item.document_type.value for item in values})),
            statuses=tuple(sorted({item.status for item in values})),
            earliest_date=dates[0] if dates else None,
            latest_date=dates[-1] if dates else None,
            tags=tuple(sorted({tag for item in values for tag in item.tags}))[:100],
            incident_count=sum(item.document_type.value == "incident" for item in values),
            policy_count=sum(item.document_type.value == "policy" for item in values),
            runbook_count=sum(item.document_type.value == "runbook" for item in values),
            architecture_document_count=sum(
                item.document_type.value == "architecture" for item in values
            ),
        )
