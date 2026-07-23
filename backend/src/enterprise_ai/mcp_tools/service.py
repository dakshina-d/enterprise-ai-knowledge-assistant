"""Authorization, deterministic selection, tracing, and response boundary for MCP."""

import re
from collections.abc import Callable
from datetime import date

from enterprise_ai.mcp_tools.client import MCPEnterpriseClient, result_count
from enterprise_ai.mcp_tools.data import SERVICE_NAMES
from enterprise_ai.mcp_tools.errors import MCPAuthorizationError, MCPInputError
from enterprise_ai.mcp_tools.models import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    TRANSPORT_TYPE,
    GetChangeWindowsArguments,
    GetOperationalMetricsArguments,
    GetServiceProfileArguments,
    MCPExecutionResult,
    MCPProvenance,
    MCPToolResult,
    MetricPeriod,
    OperationalMetrics,
    SelectedMCPTool,
    ServiceProfile,
)
from enterprise_ai.mcp_tools.server import create_server
from enterprise_ai.models.identity import AuthenticatedPrincipal, ToolPermission
from enterprise_ai.observability.tracing import SafeTracer
from enterprise_ai.security.authorization import AuthorizationService

_UNSAFE_QUERY = re.compile(
    r"[\x00-\x1f\x7f]|\.\.[\\/]|https?://|\$\(|role\s*=|permissions?\s*=|"
    r"allowed_roles|ignore previous instructions",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def select_mcp_tool(query: str) -> SelectedMCPTool:
    """Select one allowlisted tool and exact service without model involvement."""
    if len(query) > 4_000 or _UNSAFE_QUERY.search(query):
        raise MCPInputError("MCP request contains an unsafe selector")
    value = query.casefold()
    matched = [name for name in SERVICE_NAMES if re.search(rf"\b{re.escape(name)}\b", value)]
    if len(matched) != 1:
        raise MCPInputError("MCP request requires one exact service name")
    service_name = matched[0]
    if any(
        term in value
        for term in ("p95", "latency", "availability", "error rate", "request count", "metrics")
    ):
        period = (
            MetricPeriod.DAYS_7
            if "7d" in value or "7 day" in value
            else MetricPeriod.CURRENT
            if "current" in value
            else MetricPeriod.HOURS_24
        )
        return SelectedMCPTool(
            tool_name="get_operational_metrics",
            service_name=service_name,
            period=period,
        )
    if any(term in value for term in ("change", "deployment", "maintenance", "release window")):
        try:
            dates = tuple(date.fromisoformat(item) for item in _ISO_DATE.findall(value))
        except ValueError as error:
            raise MCPInputError("MCP request contains an invalid date") from error
        if len(dates) > 2:
            raise MCPInputError("MCP request has too many dates")
        return SelectedMCPTool(
            tool_name="get_change_windows",
            service_name=service_name,
            start_date=dates[0] if dates else None,
            end_date=dates[1] if len(dates) == 2 else None,
        )
    if any(
        term in value
        for term in ("who owns", "owner", "team", "department", "tier", "criticality", "support")
    ):
        return SelectedMCPTool(
            tool_name="get_service_profile",
            service_name=service_name,
        )
    raise MCPInputError("MCP request does not identify a supported read-only operation")


class MCPEnterpriseService:
    """Revalidate authorization before constructing any MCP client or session."""

    def __init__(
        self,
        authorization: AuthorizationService | None = None,
        client_factory: Callable[[], MCPEnterpriseClient] | None = None,
        tracer: SafeTracer | None = None,
    ) -> None:
        self._authorization = authorization or AuthorizationService()
        self._client_factory = client_factory or (lambda: MCPEnterpriseClient(create_server()))
        self._tracer = tracer or SafeTracer()

    async def discover_tools(self, principal: AuthenticatedPrincipal) -> tuple[str, ...]:
        self._require_authorized(principal)
        return await self._client_factory().discover_tools()

    async def execute(
        self,
        principal: AuthenticatedPrincipal,
        selection: SelectedMCPTool,
    ) -> MCPExecutionResult:
        self._require_authorized(principal)
        metadata = {
            "server_name": SERVER_NAME,
            "tool_name": selection.tool_name,
            "user_role": principal.identity.role,
            "route": "mcp_tool",
            "protocol_version": PROTOCOL_VERSION,
            "transport_type": TRANSPORT_TYPE,
        }
        async with self._tracer.span("enterprise_ai.mcp", "tool", metadata) as parent:
            client = self._client_factory()
            async with self._tracer.span("enterprise_ai.mcp.call", "tool", metadata) as call_span:
                result = await self._call(client, selection)
                if call_span is not None:
                    call_span.update_metadata(
                        {"result_status": "completed", "result_count": result_count(result)}
                    )
            if parent is not None:
                parent.update_metadata(
                    {"result_status": "completed", "result_count": result_count(result)}
                )
        provenance = MCPProvenance(
            tool_name=selection.tool_name,
            record_identifier=selection.service_name,
            snapshot_timestamp=(
                result.snapshot_timestamp if isinstance(result, OperationalMetrics) else None
            ),
        )
        return MCPExecutionResult(
            tool_name=selection.tool_name,
            result=result,
            provenance=provenance,
            response_text=_response(result),
        )

    def _require_authorized(self, principal: AuthenticatedPrincipal) -> None:
        if not self._authorization.has_permission(principal, ToolPermission.MCP_TOOLS):
            raise MCPAuthorizationError("MCP enterprise tools are not permitted")

    @staticmethod
    async def _call(
        client: MCPEnterpriseClient,
        selection: SelectedMCPTool,
    ) -> MCPToolResult:
        if selection.tool_name == "get_service_profile":
            return await client.get_service_profile(
                GetServiceProfileArguments(service_name=selection.service_name)
            )
        if selection.tool_name == "get_operational_metrics":
            return await client.get_operational_metrics(
                GetOperationalMetricsArguments(
                    service_name=selection.service_name,
                    period=selection.period or MetricPeriod.HOURS_24,
                )
            )
        return await client.get_change_windows(
            GetChangeWindowsArguments(
                service_name=selection.service_name,
                start_date=selection.start_date,
                end_date=selection.end_date,
            )
        )


def _response(result: MCPToolResult) -> str:
    source = "Source: Fictional enterprise MCP data."
    if isinstance(result, ServiceProfile):
        return (
            f"{result.service_name} is owned by {result.owning_team} in "
            f"{result.department}; tier {result.tier.value}, criticality "
            f"{result.criticality.value}, support {result.support_hours}, lifecycle "
            f"{result.lifecycle_status.value}. {source}"
        )
    if isinstance(result, OperationalMetrics):
        return (
            f"{result.service_name} {result.period.value} metrics: availability "
            f"{result.availability_percentage:.2f}%, error rate "
            f"{result.error_rate_percentage:.2f}%, p95 latency {result.p95_latency_ms} ms, "
            f"request count {result.request_count}, active incidents "
            f"{result.active_incidents}. {source}"
        )
    if not result.windows:
        return f"No matching change windows were found for {result.service_name}. {source}"
    windows = "; ".join(
        f"{item.change_id} {item.change_type} from {item.start_time.isoformat()} "
        f"to {item.end_time.isoformat()} ({item.status.value})"
        for item in result.windows
    )
    return f"{result.service_name} change windows: {windows}. {source}"
