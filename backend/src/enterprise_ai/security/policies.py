"""Single-source deterministic role, tool, and retrieval policies."""

from types import MappingProxyType

from enterprise_ai.models.identity import AccessLevel, ToolPermission, UserRole
from enterprise_ai.models.tools import ToolName

ROLE_PERMISSIONS = MappingProxyType(
    {
        UserRole.VIEWER: frozenset({ToolPermission.KNOWLEDGE_SEARCH}),
        UserRole.ANALYST: frozenset(
            {
                ToolPermission.KNOWLEDGE_SEARCH,
                ToolPermission.PYTHON_ANALYSIS,
                ToolPermission.MCP_TOOLS,
            }
        ),
        UserRole.ADMINISTRATOR: frozenset(ToolPermission),
    }
)

TOOL_PERMISSIONS = MappingProxyType(
    {
        ToolName.KNOWLEDGE_SEARCH: ToolPermission.KNOWLEDGE_SEARCH,
        ToolName.PYTHON_ANALYSIS: ToolPermission.PYTHON_ANALYSIS,
        ToolName.EMPLOYEE_DIRECTORY: ToolPermission.MCP_TOOLS,
        ToolName.SERVICE_CATALOG: ToolPermission.MCP_TOOLS,
        ToolName.INCIDENT_RECORDS: ToolPermission.MCP_TOOLS,
        ToolName.ADMINISTRATIVE_INGESTION: ToolPermission.INGESTION_MANAGEMENT,
    }
)

ROLE_ACCESS_LEVELS = MappingProxyType(
    {
        UserRole.VIEWER: frozenset({AccessLevel.PUBLIC, AccessLevel.INTERNAL}),
        UserRole.ANALYST: frozenset(
            {AccessLevel.PUBLIC, AccessLevel.INTERNAL, AccessLevel.CONFIDENTIAL}
        ),
        UserRole.ADMINISTRATOR: frozenset(AccessLevel),
    }
)

if set(ROLE_PERMISSIONS) != set(UserRole) or set(ROLE_ACCESS_LEVELS) != set(UserRole):
    raise RuntimeError("every user role must have an explicit authorization policy")
if set(TOOL_PERMISSIONS) != set(ToolName):
    raise RuntimeError("every tool must have an explicit permission policy")
