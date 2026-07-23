"""Typed failures for the application-owned enterprise MCP boundary."""


class MCPEnterpriseError(Exception):
    """Base error that must be translated to safe application behavior."""


class MCPAuthorizationError(MCPEnterpriseError):
    """The authenticated principal may not use enterprise MCP tools."""


class MCPInputError(MCPEnterpriseError):
    """A tool request could not be resolved or validated safely."""


class MCPProtocolError(MCPEnterpriseError):
    """The MCP server returned an invalid or unsuccessful protocol result."""


class MCPUnavailableError(MCPEnterpriseError):
    """The local MCP transport could not be established or completed."""


class MCPTimeoutError(MCPEnterpriseError):
    """The bounded MCP operation exceeded its deadline."""
