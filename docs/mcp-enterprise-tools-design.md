# MCP enterprise tools design

## Purpose and scope

The application uses the official MCP Python SDK to access structured enterprise-system records that do not belong in the document corpus. It exposes exactly three read-only tools over a genuine MCP client/server protocol path. All records represent the fictional Lanka Horizon Commercial Bank demonstration environment and contain no personal data, credentials, or real-company information.

The dependency is bounded to `mcp>=1.28,<2`: v1.x is the stable SDK line used here, while v2 is prerelease and API-incompatible. No external network or key is required.

## Server, transport, and schemas

`enterprise-fictional-data` is an application-owned FastMCP server. Graph calls and tests use connected in-memory SDK streams, exercising initialization, discovery, protocol messages, schema validation, structured results, and shutdown without a listener or subprocess. A stdio entry point exists for manual interoperability. The authenticated host application is the security boundary; transport OAuth is not claimed.

The deterministic typed fixture contains seven services: payment gateway, card settlement, mobile banking API, customer notification, identity and access, fraud screening, and customer profile. Import-time validation rejects duplicates, inconsistent references, malformed dates, and invalid metrics.

- `get_service_profile(service_name)` returns ownership, department, tier, criticality, support hours, and lifecycle.
- `get_operational_metrics(service_name, period)` returns a current, 24-hour, or 7-day fictional snapshot.
- `get_change_windows(service_name, start_date, end_date)` returns windows within a maximum 90-day range.

The server rejects unknown tools/services, unexpected properties, unsafe names, invalid dates, reversed or oversized ranges, and instruction-like selectors. It offers no arbitrary SQL, Python, shell, filesystem, URL, prompt, or write capability. The optional `enterprise://services/catalog` resource contains only fictional canonical identifiers and lifecycle status.

## Client and authorization

`MCPEnterpriseClient` converts SDK results immediately into strict application models. Graph code cannot issue a generic tool call. Each typed method verifies the exact discovery contract, applies a bounded timeout, validates structured output, closes its session deterministically, translates protocol failures, and propagates cancellation.

`MCPEnterpriseService` requires `mcp_tools` before constructing a client, starting the in-memory server task, discovering tools, or invoking a tool. Viewers are denied without catalog, owner, metric, change, count, or protocol disclosure. Analysts and administrators are allowed. Role and permission values are never MCP arguments.

## Graph, output, events, and traces

Deterministic classification selects `mcp_tool` for exact ownership/profile, metric, and change-window requests. Policy lookup remains retrieval; incident aggregation remains Python analysis or research. `execute_mcp_tool` resolves one exact service, chooses an allowlisted tool, reauthorizes, invokes asynchronously, and stores a typed result.

Responses state `Source: Fictional enterprise MCP data`. MCP provenance is separate from document evidence and citations and contains source type, server, tool, canonical record identifier, and optional snapshot timestamp. MCP records never enter document citation validation.

Safe public events are `mcp.started`, `mcp.tool_selected`, `mcp.completed`, `mcp.denied`, and `mcp.failed`. Payloads contain only tool/server identifiers, route, structural result count, and duration category. Allowed calls create `enterprise_ai.mcp` and `enterprise_ai.mcp.call` spans with structural metadata only. Queries, arguments, owner names, metrics, change records, protocol frames, errors, and credentials are excluded. Viewer denial creates no MCP span.

## Failure behavior, verification, and limitations

Unavailable transport, discovery/call failures, invalid schemas, unknown tools, timeout, and closed sessions become typed safe failures without retry or unrestricted fallback. Cancellation propagates. Tracing failure remains isolated, and MCP failure uses the existing graph failure terminal without altering other routes.

```powershell
python -m enterprise_ai.mcp_tools.cli list-tools
python -m enterprise_ai.mcp_tools.cli call --role analyst --tool get_service_profile --service payment-gateway
python -m enterprise_ai.mcp_tools.cli call --role viewer --tool get_service_profile --service payment-gateway
python -m enterprise_ai.graph.cli run --role analyst --query "Who owns the payment-gateway service?"
```

Tests use the real SDK protocol in memory and cover contracts, authorization, malicious input, timeout, cancellation, concurrency, routing, events, provenance, tracing, and failure isolation. The dataset is intentionally static. Remote MCP deployment, OAuth, model-selected arbitrary tools, write tools, fuzzy matching, FastAPI/SSE, and Streamlit are not implemented.
