"""Real-protocol contract tests for the fictional enterprise MCP server."""

from datetime import timedelta

import pytest
from enterprise_ai.mcp_tools.data import SERVICE_NAMES
from enterprise_ai.mcp_tools.models import TOOL_NAMES
from enterprise_ai.mcp_tools.server import create_server
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.mark.asyncio
async def test_discovery_contract_is_exact_stable_and_read_only() -> None:
    async with create_connected_server_and_client_session(
        create_server(), read_timeout_seconds=timedelta(seconds=5)
    ) as session:
        result = await session.list_tools()

    assert tuple(tool.name for tool in result.tools) == TOOL_NAMES
    assert all("fictional" in (tool.description or "").casefold() for tool in result.tools)
    assert all("read-only" in (tool.description or "").casefold() for tool in result.tools)
    assert all("authorization" in (tool.description or "").casefold() for tool in result.tools)
    assert all(tool.annotations and tool.annotations.readOnlyHint for tool in result.tools)
    assert all(tool.inputSchema.get("additionalProperties") is False for tool in result.tools)


@pytest.mark.asyncio
async def test_each_tool_returns_valid_structured_content_over_mcp() -> None:
    async with create_connected_server_and_client_session(create_server()) as session:
        profile = await session.call_tool(
            "get_service_profile", {"service_name": "payment-gateway"}
        )
        metrics = await session.call_tool(
            "get_operational_metrics",
            {"service_name": "mobile-banking-api", "period": "24h"},
        )
        changes = await session.call_tool(
            "get_change_windows",
            {
                "service_name": "card-settlement",
                "start_date": "2026-07-01",
                "end_date": "2026-08-01",
            },
        )

    assert not profile.isError and profile.structuredContent
    assert profile.structuredContent["service_name"] == "payment-gateway"
    assert not metrics.isError and metrics.structuredContent
    assert metrics.structuredContent["p95_latency_ms"] > 0
    assert not changes.isError and changes.structuredContent
    assert changes.structuredContent["windows"][0]["affected_service"] == "card-settlement"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("get_service_profile", {"service_name": "unknown-service"}),
        ("get_service_profile", {"service_name": "../../secrets"}),
        ("get_service_profile", {"service_name": "$(whoami)"}),
        ("get_service_profile", {"service_name": "http://attacker.example"}),
        ("get_service_profile", {"service_name": "payment-gateway", "role": "administrator"}),
        (
            "get_change_windows",
            {
                "service_name": "payment-gateway",
                "start_date": "2026-08-01",
                "end_date": "2026-07-01",
            },
        ),
        (
            "get_change_windows",
            {
                "service_name": "payment-gateway",
                "start_date": "2026-01-01",
                "end_date": "2026-07-01",
            },
        ),
        (
            "get_change_windows",
            {"service_name": "payment-gateway", "start_date": "not-a-date"},
        ),
    ],
)
async def test_invalid_or_injected_arguments_are_rejected(
    tool_name: str, arguments: dict[str, object]
) -> None:
    async with create_connected_server_and_client_session(create_server()) as session:
        result = await session.call_tool(tool_name, arguments)

    assert result.isError
    assert result.structuredContent is None


@pytest.mark.asyncio
async def test_unknown_tool_and_catalog_are_bounded_and_deterministic() -> None:
    server = create_server()
    async with create_connected_server_and_client_session(server) as session:
        unknown = await session.call_tool("arbitrary_shell", {"command": "whoami"})
        resources = await session.list_resources()
        first = await session.read_resource("enterprise://services/catalog")
        second = await session.read_resource("enterprise://services/catalog")

    assert unknown.isError
    assert tuple(str(item.uri) for item in resources.resources) == (
        "enterprise://services/catalog",
    )
    assert first.contents == second.contents
    serialized = repr(first.contents)
    assert all(name in serialized for name in SERVICE_NAMES)
    assert "password" not in serialized.casefold()
