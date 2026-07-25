"""Central deterministic intent, complexity, and supervisor rules."""

import re

from enterprise_ai.models.graph import Intent, Route
from enterprise_ai.models.identity import (
    AccessLevel,
    AuthenticatedPrincipal,
    ToolPermission,
    UserRole,
)
from enterprise_ai.retrieval.identifiers import extract_enterprise_identifiers
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.security.guardrails import security_denial_category
from enterprise_ai.tools.python_analysis.intent import has_explicit_aggregate_intent

GREETING = re.compile(r"^(hi|hello|hey|good (morning|afternoon|evening))[!. ]*$", re.I)


def requests_inaccessible_access(
    text: str,
    principal: AuthenticatedPrincipal,
    authorization: AuthorizationService,
) -> bool:
    """Reject explicit sensitivity requests that the authenticated role cannot access."""
    value = text.casefold()
    requested = {
        level for level in AccessLevel if re.search(rf"\b{re.escape(level.value)}\b", value)
    }
    return bool(requested - authorization.allowed_access_levels(principal))


def classify(text: str) -> tuple[Intent, str]:
    value = text.casefold()
    if security_denial_category(text) is not None:
        return Intent.SECURITY_DENIAL, "security_rejected"
    identifiers = extract_enterprise_identifiers(text)
    aggregate = has_explicit_aggregate_intent(text)
    if identifiers:
        if len(identifiers) > 1 and aggregate:
            return Intent.UNSUPPORTED, "identifier_scoped_aggregate_unavailable"
        return Intent.KNOWLEDGE_LOOKUP, "exact_lookup"
    if GREETING.match(text.strip()) or "what can you do" in value:
        return Intent.CONVERSATIONAL, "simple"
    if aggregate:
        return Intent.STRUCTURED_ANALYSIS, "tool_required"
    if any(
        term in value
        for term in (
            "all incidents",
            "compare",
            "recurring root causes",
            "across departments",
            "summarize reports",
            "last year",
        )
    ):
        return Intent.CROSS_DOCUMENT_RESEARCH, "cross_document"
    if any(term in value for term in ("employee directory", "service owner", "employee lookup")):
        return Intent.ENTERPRISE_TOOL_LOOKUP, "tool_required"
    if any(
        term in value
        for term in (
            "who owns the ",
            "owning team",
            "service tier",
            "service criticality",
            "support hours",
            "p95 latency",
            "availability",
            "error rate",
            "request count",
            "planned change",
            "change window",
            "release window",
        )
    ):
        return Intent.ENTERPRISE_TOOL_LOOKUP, "tool_required"
    if any(term in value for term in ("delete index", "admin operation", "reindex namespace")):
        return Intent.ADMINISTRATIVE, "tool_required"
    if any(term in value for term in ("generate a video", "create an animation", "compose a song")):
        return Intent.UNSUPPORTED, "simple"
    return Intent.KNOWLEDGE_LOOKUP, "simple"


def supervise(
    intent: Intent, principal: AuthenticatedPrincipal, authorization: AuthorizationService
) -> Route:
    role = principal.identity.role
    if intent is Intent.SECURITY_DENIAL:
        return Route.DENY
    if intent is Intent.CONVERSATIONAL:
        return Route.DIRECT_RESPONSE
    if intent is Intent.KNOWLEDGE_LOOKUP:
        return (
            Route.SIMPLE_RETRIEVAL
            if authorization.has_permission(principal, ToolPermission.KNOWLEDGE_SEARCH)
            else Route.DENY
        )
    if intent is Intent.CROSS_DOCUMENT_RESEARCH:
        return Route.RECURSIVE_RESEARCH
    if intent is Intent.STRUCTURED_ANALYSIS:
        return (
            Route.PYTHON_ANALYSIS
            if authorization.has_permission(principal, ToolPermission.PYTHON_ANALYSIS)
            else Route.DENY
        )
    if intent is Intent.ENTERPRISE_TOOL_LOOKUP:
        return (
            Route.MCP_TOOL
            if authorization.has_permission(principal, ToolPermission.MCP_TOOLS)
            else Route.DENY
        )
    if intent is Intent.ADMINISTRATIVE:
        return Route.UNSUPPORTED if role is UserRole.ADMINISTRATOR else Route.DENY
    return Route.UNSUPPORTED


ROUTE_NODE = {
    Route.SIMPLE_RETRIEVAL: "simple_retrieval",
    Route.DIRECT_RESPONSE: "direct_response",
    Route.DENY: "deny_request",
    Route.FAILURE: "handle_failure",
    Route.RECURSIVE_RESEARCH: "cross_document_research",
    Route.PYTHON_ANALYSIS: "python_analysis",
    Route.MCP_TOOL: "execute_mcp_tool",
    Route.HUMAN_APPROVAL: "unsupported",
    Route.UNSUPPORTED: "unsupported",
}
