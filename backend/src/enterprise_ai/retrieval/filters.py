"""Server-owned Pinecone authorization and optional-filter compiler."""

from datetime import date
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enterprise_ai.models.identity import AccessLevel, AuthenticatedPrincipal
from enterprise_ai.models.retrieval import DocumentType
from enterprise_ai.security.authorization import AuthorizationService


class DenseQueryFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    departments: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = Field(
        default=(), max_length=50
    )
    document_types: tuple[DocumentType, ...] = Field(default=(), max_length=20)
    statuses: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...] = Field(
        default=(), max_length=50
    )
    created_from: date | None = None
    created_to: date | None = None
    updated_from: date | None = None
    updated_to: date | None = None
    document_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    tags: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...] = Field(
        default=(), max_length=50
    )
    access_levels: tuple[AccessLevel, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created date range is reversed")
        if self.updated_from and self.updated_to and self.updated_from > self.updated_to:
            raise ValueError("updated date range is reversed")
        return self


def build_authorization_filter(
    principal: AuthenticatedPrincipal,
    build_fingerprint: str,
    filters: DenseQueryFilters | None = None,
    authorization: AuthorizationService | None = None,
) -> dict[str, Any]:
    service = authorization or AuthorizationService()
    allowed = service.allowed_access_levels(principal)
    selected = set(filters.access_levels) if filters else set()
    if selected and not selected <= allowed:
        raise ValueError("optional access filters cannot broaden principal access")
    clauses: list[dict[str, Any]] = [
        {"build_fingerprint": {"$eq": build_fingerprint}},
        {"access_level": {"$in": sorted(level.value for level in (selected or allowed))}},
        {"allowed_roles": {"$in": [principal.identity.role.value]}},
    ]
    if filters:
        _append_optional(clauses, filters)
    return {"$and": clauses}


def _append_optional(clauses: list[dict[str, Any]], filters: DenseQueryFilters) -> None:
    mappings: tuple[tuple[str, tuple[Any, ...]], ...] = (
        ("department", filters.departments),
        ("document_type", tuple(value.value for value in filters.document_types)),
        ("status", filters.statuses),
        ("document_id", tuple(str(value) for value in filters.document_ids)),
        ("tags", filters.tags),
    )
    for field, values in mappings:
        if values:
            clauses.append({field: {"$in": list(values)}})
    for field, lower, upper in (
        ("created_day", filters.created_from, filters.created_to),
        ("updated_day", filters.updated_from, filters.updated_to),
    ):
        bounds: dict[str, float] = {}
        if lower:
            bounds["$gte"] = float((lower - date(1970, 1, 1)).days)
        if upper:
            bounds["$lte"] = float((upper - date(1970, 1, 1)).days)
        if bounds:
            clauses.append({field: bounds})
