"""FastMCP server definition for Omnissa Horizon."""
import os

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier

from . import resources
from .tools import auth, config, discovery, entitlements, external, helpdesk, inventory, monitor

# When MCP_API_KEY is set, HTTP transport requires clients to send
# Authorization: Bearer <MCP_API_KEY>. Stdio transport always skips auth.
_api_key = os.environ.get("MCP_API_KEY")
_auth = (
    StaticTokenVerifier(tokens={_api_key: {"client_id": "mcp-client", "scopes": ["mcp"]}})
    if _api_key
    else None
)

mcp = FastMCP(
    name="Horizon",
    auth=_auth,
    instructions="""MCP server for Omnissa Horizon VDI management (verified against the
Horizon Server REST API for versions 2512 through 2606).

Required environment variables:
  HORIZON_BASE_URL         Horizon Connection Server URL, e.g. https://horizon.corp.example.com
  HORIZON_ACCESS_TOKEN     Bearer token — obtain via horizon_login, then set here
  HORIZON_VERIFY_SSL       Set to 'false' to skip TLS verification (lab use only)
  MCP_TRANSPORT            Transport: 'stdio' (default) | 'streamable-http' | 'sse'
  MCP_HOST / MCP_PORT      Host/port when using HTTP transport (default 0.0.0.0:8000)
  MCP_API_KEY              (HTTP transport only) Bearer token clients must send to authenticate

Workflow:
1. Call horizon_login with AD credentials to receive access_token + refresh_token.
2. Store the access_token as HORIZON_ACCESS_TOKEN in your MCP client config and restart,
   OR the login tool will update the running server's token automatically for this session.
3. Use refresh token via horizon_refresh_token before expiry (~8 hours).

Tool groups:
  Auth         — login (SecretStr password), logout, token refresh
  Inventory    — desktop pools, machines, sessions, RDS farms, application pools
  Monitor      — get_infrastructure_health (all components), get_metrics (all scopes),
                 get_connection_server_health (per-server detail)
  Config       — connection servers, virtual centers, licenses, global policies, settings,
                 list_image_management (streams|versions|tags)
  Entitlements — list_pool_entitlements, get_pool_entitlement, set_pool_entitlements
  External     — AD user/group search, domains, audit events, vCenter resource discovery
  Help Desk    — diagnose_session (all diagnostics in one call), remote assistance
  Discovery    — get_api_coverage (lists all tools, resources, and unsupported operations)

Resources (read-only, horizon://<path>):
  horizon://config/* — RBAC, authenticators, TrueSSO, settings, infrastructure config
  horizon://monitor/* — App Volumes, event DB, RDS servers, SAML, TrueSSO, pods, datastores

Always confirm with the user before performing destructive operations
(logoff, rebuild, shutdown, delete).
""",
)

auth.register(mcp)
config.register(mcp)
discovery.register(mcp)
entitlements.register(mcp)
external.register(mcp)
helpdesk.register(mcp)
inventory.register(mcp)
monitor.register(mcp)
resources.register(mcp)
