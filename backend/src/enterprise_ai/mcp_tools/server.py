"""Official-SDK MCP server for read-only fictional enterprise data."""

import json
from collections.abc import Sequence
from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ContentBlock, Tool, ToolAnnotations

from enterprise_ai.mcp_tools.data import (
    FICTIONAL_DATA_NOTICE,
    SERVICE_CATALOG,
    SERVICE_NAMES,
    get_record,
)
from enterprise_ai.mcp_tools.models import (
    SERVER_NAME,
    ChangeWindowResult,
    GetChangeWindowsArguments,
    GetOperationalMetricsArguments,
    GetServiceProfileArguments,
    MetricPeriod,
    OperationalMetrics,
    ServiceProfile,
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_TOOL_ARGUMENTS = {
    "get_service_profile": frozenset({"service_name"}),
    "get_operational_metrics": frozenset({"service_name", "period"}),
    "get_change_windows": frozenset({"service_name", "start_date", "end_date"}),
}


class StrictFastMCP(FastMCP):
    """Close FastMCP v1's permissive-extra-argument compatibility behavior."""

    async def list_tools(self) -> list[Tool]:
        tools = await super().list_tools()
        for tool in tools:
            tool.inputSchema["additionalProperties"] = False
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        allowed = _TOOL_ARGUMENTS.get(name)
        if allowed is not None and set(arguments) - allowed:
            raise ValueError("unexpected tool arguments")
        return await super().call_tool(name, arguments)


def create_server() -> FastMCP:
    """Build a fresh local-only server with three stable read-only tools."""
    server = StrictFastMCP(
        SERVER_NAME,
        log_level="ERROR",
        instructions=(
            f"{FICTIONAL_DATA_NOTICE} The host application must authorize callers before use."
        ),
    )

    @server.tool(
        description=(
            "Return the canonical profile for one exact service_name string: owning team, "
            "department, tier, criticality, support hours, and lifecycle status. Results are "
            "fictional and read-only; authorization remains enforced by the host application."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_service_profile(service_name: str) -> ServiceProfile:
        arguments = GetServiceProfileArguments(service_name=service_name)
        return get_record(arguments.service_name).profile

    @server.tool(
        description=(
            "Return safe operational metrics for one exact service_name and optional period "
            "(current, 24h, or 7d): availability, request count, error rate, p95 latency, active "
            "incidents, and snapshot time. Results are fictional and read-only; authorization "
            "remains enforced by the host application."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_operational_metrics(
        service_name: str,
        period: MetricPeriod = MetricPeriod.HOURS_24,
    ) -> OperationalMetrics:
        arguments = GetOperationalMetricsArguments(service_name=service_name, period=period)
        record = get_record(arguments.service_name)
        return next(item for item in record.metrics if item.period is arguments.period)

    @server.tool(
        description=(
            "Return planned or approved change windows for one exact service_name, optionally "
            "bounded by ISO start_date and end_date values spanning at most 90 days. Each result "
            "contains change ID, type, times, status, service, and team. Results are fictional "
            "and read-only; authorization remains enforced by the host application."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_change_windows(
        service_name: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> ChangeWindowResult:
        arguments = GetChangeWindowsArguments(
            service_name=service_name,
            start_date=start_date,
            end_date=end_date,
        )
        windows = tuple(
            item
            for item in get_record(arguments.service_name).change_windows
            if (arguments.start_date is None or item.end_time.date() >= arguments.start_date)
            and (arguments.end_date is None or item.start_time.date() <= arguments.end_date)
        )
        return ChangeWindowResult(service_name=arguments.service_name, windows=windows)

    @server.resource(
        "enterprise://services/catalog",
        name="fictional-service-catalog",
        description=(
            "Stable discovery list of fictional service identifiers. Read-only; the host "
            "application must authorize access before opening an MCP session."
        ),
        mime_type="application/json",
    )
    def service_catalog() -> str:
        return json.dumps(
            {
                "notice": FICTIONAL_DATA_NOTICE,
                "services": [
                    {
                        "service_name": name,
                        "lifecycle_status": SERVICE_CATALOG[name].profile.lifecycle_status.value,
                    }
                    for name in SERVICE_NAMES
                ],
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    return server


def main() -> None:
    """Run the repository-owned server over local stdio for manual interoperability."""
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
