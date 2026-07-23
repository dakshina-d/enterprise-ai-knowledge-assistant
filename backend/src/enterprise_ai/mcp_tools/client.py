"""Async typed MCP client adapter that hides SDK response internals."""

import asyncio
from collections.abc import Awaitable
from datetime import timedelta
from typing import TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import ValidationError

from enterprise_ai.mcp_tools.errors import (
    MCPEnterpriseError,
    MCPProtocolError,
    MCPTimeoutError,
    MCPUnavailableError,
)
from enterprise_ai.mcp_tools.models import (
    TOOL_NAMES,
    ChangeWindowResult,
    GetChangeWindowsArguments,
    GetOperationalMetricsArguments,
    GetServiceProfileArguments,
    MCPToolResult,
    OperationalMetrics,
    ServiceProfile,
)
from enterprise_ai.models.common import ContractModel

ResultT = TypeVar("ResultT", bound=ContractModel)
BoundedT = TypeVar("BoundedT")


class MCPEnterpriseClient:
    """Use a real SDK ClientSession over bounded in-memory protocol streams."""

    def __init__(self, server: FastMCP, *, timeout_seconds: float = 5.0) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("MCP timeout must be between 0 and 30 seconds")
        self._server = server
        self._timeout_seconds = timeout_seconds

    async def discover_tools(self) -> tuple[str, ...]:
        async def operation() -> tuple[str, ...]:
            async with create_connected_server_and_client_session(
                self._server,
                read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
            ) as session:
                result = await session.list_tools()
                return tuple(tool.name for tool in result.tools)

        return await self._bounded(operation())

    async def get_service_profile(self, arguments: GetServiceProfileArguments) -> ServiceProfile:
        return await self._invoke("get_service_profile", arguments, ServiceProfile)

    async def get_operational_metrics(
        self, arguments: GetOperationalMetricsArguments
    ) -> OperationalMetrics:
        return await self._invoke("get_operational_metrics", arguments, OperationalMetrics)

    async def get_change_windows(self, arguments: GetChangeWindowsArguments) -> ChangeWindowResult:
        return await self._invoke("get_change_windows", arguments, ChangeWindowResult)

    async def _invoke(
        self,
        tool_name: str,
        arguments: ContractModel,
        result_type: type[ResultT],
    ) -> ResultT:
        if tool_name not in TOOL_NAMES:
            raise MCPProtocolError("MCP tool is not allowlisted")

        async def operation() -> ResultT:
            async with create_connected_server_and_client_session(
                self._server,
                read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
            ) as session:
                discovered = tuple(tool.name for tool in (await session.list_tools()).tools)
                if discovered != TOOL_NAMES:
                    raise MCPProtocolError("MCP discovery contract mismatch")
                result = await session.call_tool(
                    tool_name,
                    arguments=arguments.model_dump(mode="json", exclude_none=True),
                )
                if result.isError or result.structuredContent is None:
                    raise MCPProtocolError("MCP tool call failed safely")
                try:
                    return result_type.model_validate(result.structuredContent)
                except ValidationError as error:
                    raise MCPProtocolError("MCP result schema is invalid") from error

        return await self._bounded(operation())

    async def _bounded(self, operation: Awaitable[BoundedT]) -> BoundedT:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await operation
        except TimeoutError as error:
            raise MCPTimeoutError("MCP operation timed out") from error
        except MCPEnterpriseError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as error:
            typed = _find_typed_error(error)
            if typed is not None:
                raise typed from error
            raise MCPUnavailableError("MCP transport is unavailable") from error


def result_count(result: MCPToolResult) -> int:
    """Return a safe structural count without exposing result values."""
    return len(result.windows) if isinstance(result, ChangeWindowResult) else 1


def _find_typed_error(error: BaseException) -> MCPEnterpriseError | None:
    if isinstance(error, MCPEnterpriseError):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            match = _find_typed_error(nested)
            if match is not None:
                return match
    return None
