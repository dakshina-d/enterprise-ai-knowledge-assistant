"""Credential-free CLI for the local fictional enterprise MCP server."""

import argparse
import asyncio

from enterprise_ai.mcp_tools.errors import MCPEnterpriseError
from enterprise_ai.mcp_tools.models import TOOL_NAMES
from enterprise_ai.mcp_tools.service import MCPEnterpriseService
from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.evaluation import assessment_principal


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect fictional read-only MCP tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    listing = subparsers.add_parser("list-tools")
    listing.add_argument(
        "--role",
        choices=[role.value for role in UserRole],
        default=UserRole.ANALYST.value,
    )
    call = subparsers.add_parser("call")
    call.add_argument("--role", choices=[role.value for role in UserRole], required=True)
    call.add_argument("--tool", choices=TOOL_NAMES, required=True)
    call.add_argument("--service", required=True)
    call.add_argument("--period", choices=("current", "24h", "7d"), default="24h")
    call.add_argument("--start-date")
    call.add_argument("--end-date")
    return parser


async def _run(arguments: argparse.Namespace) -> int:
    service = MCPEnterpriseService()
    principal = assessment_principal(UserRole(arguments.role))
    try:
        if arguments.command == "list-tools":
            for tool in await service.discover_tools(principal):
                print(tool)
            return 0
        phrases = {
            "get_service_profile": f"Who owns the {arguments.service} service?",
            "get_operational_metrics": (
                f"Show {arguments.period} p95 latency metrics for {arguments.service}."
            ),
            "get_change_windows": (
                f"Show planned changes for {arguments.service}"
                f"{f' {arguments.start_date}' if arguments.start_date else ''}"
                f"{f' {arguments.end_date}' if arguments.end_date else ''}."
            ),
        }
        from enterprise_ai.mcp_tools.service import select_mcp_tool

        result = await service.execute(principal, select_mcp_tool(phrases[arguments.tool]))
        print(result.model_dump_json(indent=2))
        return 0
    except MCPEnterpriseError:
        print("MCP request denied or failed safely.")
        return 2


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))


if __name__ == "__main__":
    main()
