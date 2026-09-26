"""FastMCP server definition for Omnissa Horizon."""
import os

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier

from . import audit, resources
from .tools import auth, config, discovery, entitlements, external, helpdesk, inventory, monitor

# When MCP_API_KEY is set, HTTP transport requires clients to send
# Authorization: Bearer <MCP_API_KEY>. Stdio transport always skips auth.
# __main__ refuses to start HTTP transport without a key unless
# MCP_ALLOW_UNAUTHENTICATED=true.
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
  HORIZON_ACCESS_TOKEN     (optional) Bearer token; otherwise obtained via horizon_login
  HORIZON_REFRESH_TOKEN    (optional) Refresh token used to renew the access token automatically
  HORIZON_EXPOSE_TOKENS    'true' makes horizon_login/horizon_refresh_token return full tokens
  HORIZON_AUDIT_LOG        (optional) File for the JSON-lines audit log (default: stderr)
  HORIZON_VERIFY_SSL       Set to 'false' to skip TLS verification (lab use only)
  MCP_TRANSPORT            Transport: 'stdio' (default) | 'streamable-http' | 'sse'
  MCP_HOST / MCP_PORT      Host/port when using HTTP transport (default 127.0.0.1:8000)
  MCP_API_KEY              (HTTP transport, required) Bearer token clients must send to authenticate
  HORIZON_CONFIRMATION     'elicit' (default): refuse destructive ops if the client can't prompt the user;
                           'flag': accept confirm=True instead

Workflow:
1. If a tool says the session expired or no token is set, call horizon_login with AD credentials.
   The server keeps the tokens itself; only short hints are returned.
2. The server renews an expired access token (~8 hours) automatically using the stored
   refresh token. There's no need to call horizon_refresh_token or to handle tokens yourself.

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

Destructive operations (deletes, logoff/disconnect/reset, machine shutdown/restart/
reset/rebuild/archive, disabling pools or farms, revoking entitlements, changing global
policies or settings) ask the user to confirm directly in the MCP client before running.
Explain what you're about to do and why before calling them; if the user cancels, don't
retry without asking. Clients that can't show confirmation prompts are refused unless
the operator sets HORIZON_CONFIRMATION=flag.
""",
)

# Lets audit log lines name the tool that triggered them.
mcp.add_middleware(audit.ToolNameMiddleware())

auth.register(mcp)
config.register(mcp)
discovery.register(mcp)
entitlements.register(mcp)
external.register(mcp)
helpdesk.register(mcp)
inventory.register(mcp)
monitor.register(mcp)
resources.register(mcp)
