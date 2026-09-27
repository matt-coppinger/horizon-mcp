"""FastMCP server definition for Omnissa Horizon."""
import os
from collections.abc import Mapping

from fastmcp import FastMCP
from fastmcp.server.auth import TokenVerifier

from . import audit, client, identity, resources
from .tools import auth, config, discovery, entitlements, external, helpdesk, inventory, monitor
from .users import ApiKeyVerifier


def build_auth(env: Mapping[str, str] = os.environ) -> TokenVerifier | None:
    """The HTTP bearer-token verifier for the configured auth mode (stdio always skips auth).

    MCP_USERS_FILE: one key per user; the identity is the user's name (multi-user mode).
    MCP_API_KEY:    one shared key; the identity is "default" (single-user mode).
    Neither:        no auth — __main__ refuses to start HTTP transport like that unless
                    MCP_ALLOW_UNAUTHENTICATED=true.
    """
    users_file = env.get("MCP_USERS_FILE")
    if users_file:
        return ApiKeyVerifier.from_file(users_file)
    api_key = env.get("MCP_API_KEY")
    if api_key:
        return ApiKeyVerifier.single_key(api_key, identity.DEFAULT)
    return None


_auth = build_auth()
if os.environ.get("MCP_USERS_FILE") and not identity.is_multi_user():
    # Fail closed even if this module is served some other way than __main__:
    # with per-user keys there's no shared session to fall back to.
    client.configure(multi_user=True)

INSTRUCTIONS = """MCP server for Omnissa Horizon VDI management (verified against the
Horizon Server REST API for versions 2512 through 2606).

Required environment variables:
  HORIZON_BASE_URL         Horizon Connection Server URL, e.g. https://horizon.corp.example.com
  HORIZON_ACCESS_TOKEN     (optional, single-user only) Bearer token; otherwise obtained via horizon_login
  HORIZON_REFRESH_TOKEN    (optional, single-user only) Refresh token used to renew the access token
  HORIZON_EXPOSE_TOKENS    'true' makes horizon_login/horizon_refresh_token return full tokens
  HORIZON_AUDIT_LOG        (optional) File for the JSON-lines audit log (default: stderr)
  HORIZON_VERIFY_SSL       Set to 'false' to skip TLS verification (lab use only)
  MCP_TRANSPORT            Transport: 'stdio' (default) | 'streamable-http' | 'sse'
  MCP_HOST / MCP_PORT      Host/port when using HTTP transport (default 127.0.0.1:8000)
  MCP_API_KEY              (HTTP, single-user) Bearer token clients must send to authenticate
  MCP_USERS_FILE           (HTTP, multi-user) JSON file of per-user key hashes (horizon-mcp-keys)
  HORIZON_CONFIRMATION     'elicit' (default): refuse destructive ops if the client can't prompt the user;
                           'flag': accept confirm=True instead

Workflow:
1. If a tool says you're not signed in or the session expired, call horizon_login with the
   user's own AD credentials. The server keeps the tokens itself; only short hints are returned.
2. The server renews an expired access token (~8 hours) automatically using the stored
   refresh token. There's no need to call horizon_refresh_token or to handle tokens yourself.
3. On a multi-user server each API key has its own Horizon session: every user signs in
   with their own account, acts with their own Horizon permissions, and logging out
   affects only them. Never sign in with someone else's credentials.

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
"""


def create_server(auth_provider: TokenVerifier | None) -> FastMCP:
    server = FastMCP(name="Horizon", auth=auth_provider, instructions=INSTRUCTIONS)
    # Lets audit log lines name the tool that triggered them.
    server.add_middleware(audit.ToolNameMiddleware())
    for module in (auth, config, discovery, entitlements, external, helpdesk, inventory, monitor, resources):
        module.register(server)
    return server


mcp = create_server(_auth)
