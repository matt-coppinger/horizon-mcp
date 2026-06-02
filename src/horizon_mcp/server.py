"""FastMCP server definition for Omnissa Horizon."""
from fastmcp import FastMCP

from .tools import auth, config, entitlements, external, helpdesk, inventory, monitor

mcp = FastMCP(
    name="Horizon",
    instructions="""MCP server for Omnissa Horizon VDI management (API version 2512).

Required environment variables:
  HORIZON_BASE_URL         Horizon Connection Server URL, e.g. https://horizon.corp.example.com
  HORIZON_ACCESS_TOKEN     Bearer token — obtain via horizon_login, then set here
  HORIZON_VERIFY_SSL       Set to 'false' to skip TLS verification (lab use only)
  MCP_TRANSPORT            Transport: 'stdio' (default) | 'streamable-http' | 'sse'
  MCP_HOST / MCP_PORT      Host/port when using HTTP transport (default 0.0.0.0:8000)

Workflow:
1. Call horizon_login with AD credentials to receive access_token + refresh_token.
2. Store the access_token as HORIZON_ACCESS_TOKEN in your MCP client config and restart,
   OR the login tool will update the running server's token automatically for this session.
3. Use refresh token via horizon_refresh_token before expiry (~8 hours).

Tool groups:
  Auth        — login, logout, token refresh
  Inventory   — desktop pools, machines, sessions, RDS farms, application pools
  Monitor     — health metrics, connection servers, gateways, virtual centers, sessions
  Config      — connection servers, virtual centers, licenses, global policies, settings
  Entitlements — pool entitlements for users and groups
  External    — AD user/group search, domains, audit events
  Help Desk   — session diagnostics, logon timing, remote assistance tickets

Always confirm with the user before performing destructive operations
(logoff, rebuild, shutdown, delete).
""",
)

auth.register(mcp)
config.register(mcp)
entitlements.register(mcp)
external.register(mcp)
helpdesk.register(mcp)
inventory.register(mcp)
monitor.register(mcp)
