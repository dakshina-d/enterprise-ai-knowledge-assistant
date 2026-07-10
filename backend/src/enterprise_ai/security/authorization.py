"""Pure deterministic authorization service for endpoints, tools, and retrieval."""

from uuid import UUID, uuid4

from enterprise_ai.models.identity import (
    AccessLevel,
    AuthenticatedPrincipal,
    AuthorizationDecision,
    ToolPermission,
    UserRole,
)
from enterprise_ai.models.retrieval import DocumentMetadata
from enterprise_ai.models.tools import ToolAuthorizationDecision, ToolName
from enterprise_ai.security.exceptions import AuthorizationError
from enterprise_ai.security.policies import ROLE_ACCESS_LEVELS, ROLE_PERMISSIONS, TOOL_PERMISSIONS


class AuthorizationService:
    def permissions_for_role(self, role: UserRole | object) -> frozenset[ToolPermission]:
        if not isinstance(role, UserRole):
            return frozenset()
        return ROLE_PERMISSIONS.get(role, frozenset())

    def has_permission(
        self, principal: AuthenticatedPrincipal, permission: ToolPermission | object
    ) -> bool:
        expected = self.permissions_for_role(principal.identity.role)
        return isinstance(permission, ToolPermission) and permission in expected

    def permission_decision(
        self, principal: AuthenticatedPrincipal, permission: ToolPermission
    ) -> AuthorizationDecision:
        allowed = self.has_permission(principal, permission)
        return AuthorizationDecision(
            allowed=allowed,
            reason_code="authorization.allowed" if allowed else "authorization.missing_permission",
            public_explanation=(
                "The operation is permitted."
                if allowed
                else "Your role does not permit this operation."
            ),
            required_permission=permission,
        )

    def require_permission(
        self, principal: AuthenticatedPrincipal, permission: ToolPermission
    ) -> None:
        if not self.has_permission(principal, permission):
            raise AuthorizationError(reason_code="authorization.missing_permission")

    def authorize_tool(
        self,
        principal: AuthenticatedPrincipal,
        tool_name: ToolName | object,
        tool_call_id: UUID | None = None,
    ) -> ToolAuthorizationDecision:
        permission = TOOL_PERMISSIONS.get(tool_name) if isinstance(tool_name, ToolName) else None
        if permission is None:
            return ToolAuthorizationDecision(
                tool_call_id=tool_call_id or uuid4(),
                allowed=False,
                reason_code="authorization.unknown_tool",
                public_explanation="The requested tool is not permitted.",
                required_permission=None,
            )
        allowed = self.has_permission(principal, permission)
        return ToolAuthorizationDecision(
            tool_call_id=tool_call_id or uuid4(),
            allowed=allowed,
            reason_code="authorization.allowed" if allowed else "authorization.missing_permission",
            public_explanation=(
                "The tool is permitted." if allowed else "Your role does not permit this tool."
            ),
            required_permission=permission,
        )

    def allowed_access_levels(self, principal: AuthenticatedPrincipal) -> frozenset[AccessLevel]:
        return ROLE_ACCESS_LEVELS.get(principal.identity.role, frozenset())

    def allowed_document_roles(self, principal: AuthenticatedPrincipal) -> frozenset[UserRole]:
        return frozenset({principal.identity.role})

    def is_document_authorized(
        self, principal: AuthenticatedPrincipal, metadata: DocumentMetadata | object
    ) -> bool:
        if not isinstance(metadata, DocumentMetadata):
            return False
        return (
            metadata.access_level in self.allowed_access_levels(principal)
            and principal.identity.role in metadata.allowed_roles
        )
