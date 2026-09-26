# Horizon MCP Server

MCP (Model Context Protocol) server for [Omnissa Horizon](https://www.omnissa.com/products/horizon/) VDI management. Exposes the Horizon REST API as MCP tools covering inventory, monitoring, configuration, entitlements, Active Directory, and help desk functions. Verified against the Horizon Server REST API spec for versions 2512 through 2606 — call `get_api_coverage` for the full list of supported tools and known gaps.

## Quickstart

The fastest path to a working setup, using Claude Code with stdio transport:

1. **Clone and install:**
   ```bash
   git clone https://github.com/matt-coppinger/horizon-mcp.git
   cd horizon-mcp
   uv sync
   ```
2. **Register the server** with Claude Code (see [Configuration](#configuration) below for what each variable means):
   ```bash
   claude mcp add horizon \
     -e HORIZON_BASE_URL=https://horizon.corp.example.com \
     -- uv run --project /absolute/path/to/horizon-mcp horizon-mcp
   ```
   Use the absolute path to where you cloned the repo. Omit `HORIZON_ACCESS_TOKEN` for now — you'll get one in the next step.
3. **Restart Claude Code**, then get a token by asking it to call `horizon_login` (see [Getting an Access Token](#getting-an-access-token)) with your AD credentials.
4. **Verify it works** — ask Claude Code to call `list_desktop_pools` or `get_infrastructure_health`. If you get real data back, you're set. To avoid logging in again after a restart, re-register with the `access_token` from step 3: `claude mcp remove horizon`, then repeat step 2 with `-e HORIZON_ACCESS_TOKEN=<token>` added.

Running the server standalone over HTTP instead (for remote/multi-user access, or in Docker)? See [HTTP (remote)](#http-remote) and [Docker](#docker).

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Horizon Connection Server 2512 or later

## Installation

```bash
git clone https://github.com/matt-coppinger/horizon-mcp.git
cd horizon-mcp
uv sync
```

## Configuration

The server reads configuration from environment variables:

| Variable | Required | Description |
|---|---|---|
| `HORIZON_BASE_URL` | Yes | Connection Server URL, e.g. `https://horizon.corp.example.com` |
| `HORIZON_ACCESS_TOKEN` | Yes* | Bearer token — obtain via `horizon_login` tool |
| `HORIZON_VERIFY_SSL` | No | Set to `false` to skip TLS cert verification (lab use only) |
| `HORIZON_CONFIRMATION` | No | `elicit` (default): destructive tools ask the user to confirm in the MCP client, and are refused if the client can't show the prompt. `flag`: fall back to a `confirm=True` argument for clients without elicitation. See [Confirming destructive operations](#confirming-destructive-operations) |
| `HORIZON_MAX_BULK_DESTRUCTIVE` | No | Most machines `machine_action` will rebuild, reset or archive in one call (default `20`) |
| `HORIZON_MAX_MACHINE_COUNT` | No | Largest machine / RDS server count `create_desktop_pool` / `create_rdsh_farm` will accept (default `500`) |
| `MCP_TRANSPORT` | No | `stdio` (default), `streamable-http`, or `sse` |
| `MCP_HOST` | No | Bind host for HTTP transport (default `127.0.0.1`; the Docker image sets `0.0.0.0`) |
| `MCP_PORT` | No | Port for HTTP transport (default `8000`) |
| `MCP_API_KEY` | HTTP only | Required for HTTP transport — clients must send `Authorization: Bearer <value>`. The server refuses to start without it |
| `MCP_ALLOW_UNAUTHENTICATED` | No | Set to `true` to run HTTP transport without `MCP_API_KEY` (not recommended) |
| `MCP_ALLOWED_HOSTS` | No | Comma-separated host names the HTTP server answers to (Host header check). Defaults to loopback names when bound to loopback; unchecked otherwise |
| `MCP_ALLOWED_ORIGINS` | No | Comma-separated browser origins allowed to call the HTTP server, e.g. `https://app.example.com`. Loopback origins are allowed when bound to loopback |

*`HORIZON_ACCESS_TOKEN` can also be obtained at runtime by calling the `horizon_login` tool.

## Usage

### stdio (Claude Desktop / Claude Code)

Add to your MCP client configuration:

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "horizon": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/HorizonMCP", "horizon-mcp"],
      "env": {
        "HORIZON_BASE_URL": "https://horizon.corp.example.com",
        "HORIZON_ACCESS_TOKEN": "your-access-token-here"
      }
    }
  }
}
```

**Claude Code** — register it with `claude mcp add` (add `--scope project` to write a shareable `.mcp.json` instead):
```bash
claude mcp add horizon \
  -e HORIZON_BASE_URL=https://horizon.corp.example.com \
  -e HORIZON_ACCESS_TOKEN=your-access-token-here \
  -- uv run --project /path/to/HorizonMCP horizon-mcp
```

### HTTP (remote)

HTTP transport requires `MCP_API_KEY` — clients authenticate with `Authorization: Bearer <MCP_API_KEY>`, and the server refuses to start without it (set `MCP_ALLOW_UNAUTHENTICATED=true` to override, not recommended). It binds to `127.0.0.1` by default; set `MCP_HOST=0.0.0.0` to accept connections from other machines.

```bash
MCP_TRANSPORT=streamable-http \
MCP_PORT=8000 \
MCP_API_KEY=your-secret-key \
HORIZON_BASE_URL=https://horizon.corp.example.com \
HORIZON_ACCESS_TOKEN=your-token \
horizon-mcp
```

The server exposes a single endpoint at `http://host:8000/mcp`.

Clients pass the key as a header. For Claude Code:

```bash
claude mcp add --transport http horizon http://your-server:8000/mcp \
  --header "Authorization: Bearer your-secret-key"
```

stdio transport always skips authentication regardless of `MCP_API_KEY`.

The HTTP server also checks `Host` and `Origin` headers to block DNS-rebinding attacks from web pages. When bound to loopback it only answers to `localhost`/`127.0.0.1`/`::1`; behind a reverse proxy or on a named host, list your host names in `MCP_ALLOWED_HOSTS`. Browser-based clients from other origins must be listed in `MCP_ALLOWED_ORIGINS`; non-browser MCP clients send no `Origin` and are unaffected.

> **HTTP transport security:** For any non-localhost deployment, place the server behind a reverse proxy (nginx, Caddy, Traefik) that enforces TLS. Each user should run a separate server instance with their own `HORIZON_ACCESS_TOKEN` and `MCP_API_KEY` to maintain session isolation.

### Docker

The provided `Dockerfile` runs the server with `streamable-http` transport (Docker containers don't have an interactive stdio channel for an MCP client to attach to, so HTTP is the practical option here).

```bash
docker build -t horizon-mcp .
docker run -d -p 8000:8000 \
  -e HORIZON_BASE_URL=https://horizon.corp.example.com \
  -e HORIZON_ACCESS_TOKEN=your-token \
  -e MCP_API_KEY=your-secret-key \
  horizon-mcp
```

Or with `docker-compose.yml` (reads `HORIZON_BASE_URL`, `HORIZON_ACCESS_TOKEN`, `HORIZON_VERIFY_SSL`, and `MCP_API_KEY` from your shell environment or a `.env` file):

```bash
HORIZON_BASE_URL=https://horizon.corp.example.com MCP_API_KEY=your-secret-key docker compose up -d
```

`MCP_API_KEY` is required — both `docker-compose.yml` and the server itself refuse to start without it, because a containerized deployment is reachable over the network by definition, so leaving the endpoint unauthenticated is not a safe default (see [Security Notes](#security-notes)). Point your MCP client at `http://host:8000/mcp` with the matching `Authorization: Bearer` header as shown above.

## Getting an Access Token

If you don't have a token yet, omit `HORIZON_ACCESS_TOKEN` from the config and call `horizon_login` as the first tool:

```
Call horizon_login with:
  username: jsmith
  password: ******   ← treated as a secret, masked in server logs
  domain: CORP
  base_url: https://horizon.corp.example.com
```

The tool returns `access_token` and `refresh_token`, and immediately activates the new token for the current server session. Copy the `access_token` value into your MCP client config and restart the server to persist it across restarts.

> **Security:** Treat `access_token` and `refresh_token` as passwords. After copying the token to your config, clear it from the conversation context. Do not commit tokens to version control.

Use `horizon_refresh_token` with the `refresh_token` to renew the access token (~8 hour expiry) without re-entering credentials.

## Available Tools

⚠️ = asks you to confirm before running — see [Confirming destructive operations](#confirming-destructive-operations).

### Auth
| Tool | Description |
|---|---|
| `horizon_login` | Authenticate with AD credentials (password masked in logs), returns access + refresh tokens |
| `horizon_refresh_token` | Refresh an expired access token |
| `horizon_logout` | Invalidate current session |

### Inventory
| Tool | Description |
|---|---|
| `list_desktop_pools` | List all VDI and RDS desktop pools (paginated) |
| `get_desktop_pool` | Get pool details |
| `create_desktop_pool` | Create a new desktop pool (VDI or RDS, automated or manual) |
| `update_desktop_pool` | Update an existing desktop pool's configuration |
| `delete_desktop_pool` | Delete a desktop pool and all its machines ⚠️ |
| `desktop_pool_action` | Enable/disable a pool, or enable/disable-provisioning (⚠️ when disabling) |
| `list_machines` | List virtual desktops (filterable by pool, state; paginated) |
| `get_machine` | Get machine details |
| `machine_action` | Shutdown, restart, reset, rebuild, archive ⚠️; recover, enter/exit maintenance |
| `assign_machine_users` | Assign or unassign users to a dedicated (non-floating) desktop |
| `list_rdsh_farms` | List RDS farms (paginated) |
| `get_rdsh_farm` | Get farm details |
| `create_rdsh_farm` | Create a new RDS farm (automated or manual) |
| `update_rdsh_farm` | Update an existing RDS farm's configuration |
| `delete_rdsh_farm` | Delete an RDS farm and all its servers ⚠️ |
| `rdsh_farm_action` | Enable or disable one or more RDS farms (⚠️ when disabling) |
| `list_application_pools` | List published application pools (paginated) |
| `get_application_pool` | Get application pool details |
| `create_application_pool` | Publish a new application pool from an RDS farm |
| `update_application_pool` | Update an existing application pool's configuration |
| `delete_application_pool` | Unpublish an application pool ⚠️ |
| `list_sessions` | List active user sessions (paginated) |
| `get_session` | Get session details |
| `disconnect_sessions` | Disconnect sessions (keep running) ⚠️ |
| `logoff_sessions` | Log off sessions (terminates apps) ⚠️ |
| `reset_or_restart_sessions` | Hard-reset or gracefully restart the VMs backing sessions ⚠️ |
| `send_message_to_sessions` | Send pop-up notification to sessions |

### Monitor
| Tool | Description |
|---|---|
| `get_infrastructure_health` | Health across all components in one parallel call (summary, connection servers, gateways, vCenters, AD domains, farms) |
| `get_metrics` | Capacity metrics in one parallel call (pools, sessions, machines, system, RDS servers, license) |
| `get_connection_server_health` | Detailed health for a specific Connection Server |

### Config
| Tool | Description |
|---|---|
| `list_connection_servers` | List connection servers |
| `get_connection_server` | Get connection server config |
| `list_virtual_centers` | List configured vCenters |
| `get_environment_properties` | Environment version and features |
| `get_settings` | Global Horizon settings |
| `update_settings` | Change a settings section: general, security, client, feature or agent-restriction ⚠️ |
| `get_global_policies` | USB, clipboard, multimedia policies |
| `update_global_policies` | Change global policies ⚠️ (the prompt lists each field being changed) |
| `list_licenses` | License list and status |
| `get_event_database` | Event DB config |
| `list_ic_domain_accounts` | Instant clone domain accounts |
| `list_image_management` | Image management streams, versions, or tags (pass `resource`: `streams`\|`versions`\|`tags`; versions and tags also need `stream_id` from `streams`) |
| `list_gateways` | Registered UAGs |
| `trigger_connection_server_backup` | Trigger Connection Server backup |

### Entitlements
| Tool | Description |
|---|---|
| `list_pool_entitlements` | All entitlements for desktop or application pools |
| `get_pool_entitlement` | Users/groups for a specific pool |
| `set_pool_entitlements` | Add, replace ⚠️, or remove ⚠️ entitlements (desktop or application) — `replace` is desktop-pool only, the Horizon API has no bulk-replace endpoint for application pools |

### External / Active Directory
| Tool | Description |
|---|---|
| `search_ad_users_or_groups` | Find AD users and groups (paginated) |
| `get_ad_user_or_group` | Get AD entity details |
| `list_ad_domains` | List configured AD domains |
| `list_ad_containers` | AD containers (OUs) in a domain — `rdn` → `ad_container_rdn` for provisioning |
| `get_domain_netbios_map` | NETBIOS → DNS domain name map |
| `list_audit_events` | Administrative audit log (paginated) |
| `list_base_vms` | VMs available for pool base images |
| `list_base_vm_snapshots` | Snapshots of a base VM (snapshot_id for instant clone pools) |
| `list_datastores` | Datastores for provisioning (requires vcenter_id + host_or_cluster_id) |
| `list_vm_folders` | VM folders in vCenter |
| `list_datacenters` | Datacenters in a vCenter Server |
| `list_hosts_or_clusters` | Hosts and clusters in a datacenter |
| `list_resource_pools` | Resource pools on a host or cluster |
| `list_network_labels` | Network port groups on a host or cluster |
| `list_network_interface_cards` | NICs on a base VM or VM template (requires `base_vm_id` or `vm_template_id`; id → `network_interface_card_id` in `nics`) |
| `list_vm_templates` | VM templates for full/linked-clone pools |
| `list_datastore_clusters` | Storage DRS datastore clusters (requires vcenter_id + host_or_cluster_id) |
| `list_customization_specifications` | Sysprep/QuickPrep specs for OS customization during provisioning |

### Discovery
| Tool | Description |
|---|---|
| `get_api_coverage` | Lists all tools, resources, and unsupported operations — call this to understand what can be managed via this server |

### Resources (read-only)

MCP Resources expose read-only Horizon data without consuming tool slots. Access them via `horizon://<path>` using your MCP client's resource protocol.

**Config resources** (`horizon://config/...`):

| URI | Description |
|---|---|
| `horizon://config/roles` | RBAC roles and their privileges |
| `horizon://config/permissions` | Role-to-principal permission assignments |
| `horizon://config/privileges` | All selectable admin privileges |
| `horizon://config/local-access-groups` | Local access groups for admin delegation |
| `horizon://config/federation-access-groups` | CPA federation access groups |
| `horizon://config/saml-authenticators` | SAML 2.0 authenticator configurations |
| `horizon://config/radius-authenticators` | RADIUS authenticator configurations |
| `horizon://config/gssapi-authenticators` | GSSAPI/Kerberos authenticator configurations |
| `horizon://config/jwt-authenticators` | JWT authenticator configurations |
| `horizon://config/app-volumes-managers` | App Volumes Managers registered with Horizon |
| `horizon://config/uem-servers` | User Environment Manager servers |
| `horizon://config/true-sso` | TrueSSO connector configurations |
| `horizon://config/true-sso-enrollment-servers` | TrueSSO enrollment servers |
| `horizon://config/compute-profiles` | Compute profiles for provisioning |
| `horizon://config/customization-specifications` | Sysprep/QuickPrep specs (config view) |
| `horizon://config/settings/general` | General settings |
| `horizon://config/settings/security` | Security settings |
| `horizon://config/settings/client` | Client feature settings |
| `horizon://config/settings/feature` | Feature toggle settings |
| `horizon://config/settings/agent-restriction` | Allowed agent versions/types |
| `horizon://config/syslog` | Syslog configuration |
| `horizon://config/ceip` | CEIP enrollment status |
| `horizon://config/url-redirection` | URL content redirection rules |
| `horizon://config/pre-logon-settings` | Pre-logon banner/message settings |
| `horizon://config/log-collector/log-levels` | Component log levels |
| `horizon://config/log-collector/tasks` | Log collection tasks |
| `horizon://config/gateway-access-users-or-groups` | Users and groups with gateway access |
| `horizon://config/unauthenticated-access-users` | Users configured for unauthenticated (kiosk) access |
| `horizon://config/users-or-groups-global-summary` | Global summary of admin users and groups across pods |
| `horizon://config/external-deployments` | External deployments (e.g. Horizon Cloud links) registered with this pod |
| `horizon://config/secondary-credentials` | Secondary credentials configured for connection servers |
| `horizon://config/message-clients` | Message security mode clients registered with Horizon |
| `horizon://config/rcx-servers` | RCX (Remote Console) servers registered with Horizon |

**Monitor resources** (`horizon://monitor/...`):

| URI | Description |
|---|---|
| `horizon://monitor/app-volumes-managers` | App Volumes Manager health |
| `horizon://monitor/event-database` | Event database status |
| `horizon://monitor/rds-servers` | RDS server health and session load |
| `horizon://monitor/saml-authenticators` | SAML authenticator health |
| `horizon://monitor/true-sso` | TrueSSO health and certificate status |
| `horizon://monitor/datastores/usage-metrics` | Datastore usage per pool/farm |
| `horizon://monitor/pods` | Remote pod health (CPA) |
| `horizon://monitor/pods/global-session-metrics` | Aggregate session counts across pods |
| `horizon://monitor/message-clients` | Message client health |

### Help Desk
| Tool | Description |
|---|---|
| `diagnose_session` | All session diagnostics in one parallel call: logon timing, display performance, historical performance, processes, remote applications |
| `get_remote_assistance_ticket` | MSRA ticket for remote support |
| `end_remote_application` | Force-close a published app in a session ⚠️ |

## Horizon Filter Syntax

Most list tools accept a `filter` parameter using Horizon's JSON filter format:

```json
// Equals
{"type": "Equals", "name": "state", "value": "AVAILABLE"}

// Contains (string)
{"type": "Contains", "name": "name", "value": "win11"}

// AND combination
{
  "type": "And",
  "filters": [
    {"type": "Equals", "name": "desktop_pool_id", "value": "pool-id"},
    {"type": "Equals", "name": "state", "value": "CONNECTED"}
  ]
}
```

## Paginated List Results

Tools marked *(paginated)* in the tables above (`list_desktop_pools`, `list_machines`, `list_rdsh_farms`, `list_application_pools`, `list_sessions`, `search_ad_users_or_groups`, `list_audit_events`) take `page` (1-based) and `size`, and return an envelope rather than a bare list:

```json
{
  "items": [ ... ],
  "count": 100,
  "page": 1,
  "size": 100,
  "pages_fetched": 1,
  "has_more": true,
  "next_page": 2,
  "truncated": false
}
```

- **`has_more` / `next_page`** — call the tool again with `page=next_page` to continue. The Horizon REST API returns a bare array with no "more records" indicator, so `has_more` is inferred: it is `true` whenever a full page (`size` items) came back. When the total is an exact multiple of `size`, the next page simply comes back empty.
- **`fetch_all=true`** — fetches successive pages starting at `page`, stopping at the first short page or after 10 pages / 5,000 items, whichever comes first. If it stops at the cap with more possibly remaining, `truncated` is `true` and `next_page` says where to resume. Prefer a `filter` when you only need a subset.

## Creating Pools and Farms

`create_desktop_pool` and `create_rdsh_farm` accept a `spec` dict that maps directly to the Horizon REST API request body.

> **The nesting is not what the field names suggest.** `vcenter_id` is top-level, not inside `provisioning_settings`. Datastores live under a separate top-level `storage_settings` block. AD/domain-join settings live under a separate top-level `customization_settings` block. Naming and machine count live under a separate top-level `pattern_naming_settings` block, and the count field is `max_number_of_machines`, not `max_machine_count`. The example below is **verified against a live Horizon 2606 server** (a real pool was created with this exact shape) — an earlier version of this doc had the wrong nesting throughout and would have produced a 400 on every field.

**Automated Instant Clone desktop pool (minimum working example):**
```json
{
  "name": "MyPool",
  "display_name": "My Pool",
  "type": "AUTOMATED",
  "source": "INSTANT_CLONE",
  "user_assignment": "FLOATING",
  "naming_method": "PATTERN",
  "access_group_id": "<id from the horizon://config/local-access-groups resource>",
  "vcenter_id": "<id from list_virtual_centers>",
  "provisioning_settings": {
    "parent_vm_id": "<id from list_base_vms>",
    "base_snapshot_id": "<id from list_base_vm_snapshots>",
    "datacenter_id": "<id from list_datacenters>",
    "vm_folder_id": "<id from list_vm_folders>",
    "host_or_cluster_id": "<id from list_hosts_or_clusters>",
    "resource_pool_id": "<id from list_resource_pools>"
  },
  "storage_settings": {
    "datastores": [{"datastore_id": "<id from list_datastores>"}]
  },
  "customization_settings": {
    "customization_type": "CLONE_PREP",
    "ad_container_rdn": "<rdn from list_ad_containers>",
    "instant_clone_domain_account_id": "<id from list_ic_domain_accounts>"
  },
  "pattern_naming_settings": {
    "naming_pattern": "MyPool-{n:fixed=2}",
    "max_number_of_machines": 10
  }
}
```

`nics` is optional and top-level (`[{"network_interface_card_id": "...", "network_label_assignment_specs": [...]}]`) — if omitted, new machines simply inherit the parent image's existing network settings, which is fine for most cases.

`create_rdsh_farm` requires `access_group_id` directly, and nests everything else **one level deeper**, under a top-level `automated_farm_settings` object: `automated_farm_settings.vcenter_id`, `.provisioning_settings`, `.storage_settings`, `.customization_settings`, `.pattern_naming_settings` (with `max_number_of_rds_servers` instead of `max_number_of_machines`), plus a required `max_session_type` (`LIMITED` | `UNLIMITED` — `max_sessions` is required when `LIMITED`). This shape is verified live against a real Horizon 2606 server.

**Resource ID lookup chain** — follow this sequence to resolve all IDs before calling `create_desktop_pool` or `create_rdsh_farm`:

```
list_virtual_centers
  ├─ list_customization_specifications(vcenter_id)   ← Sysprep spec ID (SYS_PREP only)
  ├─ list_vm_templates(vcenter_id)                   ← template_id (full/linked-clone pools)
  │    └─ list_network_interface_cards(vcenter_id, vm_template_id=...)  ← optional, nics
  └─ list_datacenters(vcenter_id)
       ├─ list_vm_folders(vcenter_id, datacenter_id)
       └─ list_hosts_or_clusters(vcenter_id, datacenter_id)
            ├─ list_datastores(vcenter_id, host_or_cluster_id)
            ├─ list_datastore_clusters(vcenter_id, host_or_cluster_id)
            ├─ list_resource_pools(vcenter_id, host_or_cluster_id)
            └─ list_network_labels(vcenter_id, host_or_cluster_id)  ← optional, nics
list_base_vms(vcenter_id)                            ← parent_vm_id (instant-clone pools)
  ├─ list_base_vm_snapshots(vcenter_id, base_vm_id)  ← base_snapshot_id
  └─ list_network_interface_cards(vcenter_id, base_vm_id)  ← optional, nics
horizon://config/local-access-groups (resource)      ← access_group_id (always required)
list_ad_domains
  └─ list_ad_containers(domain_id)                   ← ad_container_rdn (instant clone)
list_ic_domain_accounts                              ← instant_clone_domain_account_id (instant clone)
```

`create_application_pool` uses explicit parameters instead — pass `name`, `farm_id`, `executable_path`, and optional fields directly.

For updates, retrieve the current config with `get_desktop_pool` / `get_rdsh_farm` / `get_application_pool`, modify the relevant fields, and pass the result to the corresponding `update_*` tool. `get_desktop_pool` and `get_rdsh_farm` return every field their `update_*` schema needs, and the unchanged get-then-update round trip is verified live against Horizon 2606 for both pools and farms.

**Delete operations** (`delete_desktop_pool`, `delete_rdsh_farm`, `delete_application_pool`) ask you to confirm in the client, naming the pool or farm. Call `get_desktop_pool` / `get_rdsh_farm` and `list_sessions` first so you know what will be affected.

## Confirming destructive operations

Tools marked ⚠️ pause and ask **you** to confirm before they run, using MCP [elicitation](https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation): your MCP client shows a prompt describing exactly what will happen (for example *"Delete desktop pool Sales (id), all of its machines, and end any active sessions in it"*) with **Proceed** and **Cancel**. The AI model can't answer this prompt for you, so a prompt-injected or mistaken model can't push a destructive operation through on its own — unlike a `confirm=True` argument, which the model sets itself.

| Tool | Asks when |
|---|---|
| `delete_desktop_pool`, `delete_rdsh_farm`, `delete_application_pool` | Always |
| `machine_action` | `shutdown`, `restart`, `reset`, `rebuild`, `archive` (not `recover` or maintenance mode) |
| `logoff_sessions`, `disconnect_sessions`, `reset_or_restart_sessions` | Always |
| `end_remote_application` | Always |
| `desktop_pool_action`, `rdsh_farm_action` | Disabling (not enabling) |
| `set_pool_entitlements` | `replace` or `remove` (not `add`) |
| `update_global_policies`, `update_settings` | Always — the prompt lists each field that changes, old → new |

If your client doesn't support elicitation, these tools are **refused** by default. If you can't switch clients, set `HORIZON_CONFIRMATION=flag` on the server to accept a `confirm=True` argument instead — be aware the model can set that argument itself, so only do this with a client that asks you to approve each tool call.

These tools, plus the `update_*` tools and `assign_machine_users`, also carry `destructiveHint=True`, so clients that gate tool calls on MCP annotations will prompt before running them.

## Running Tests

```bash
uv run pytest tests/ -v
```

## Security Notes

- Store credentials in your MCP client's `env` block, not in code or config files tracked by git.
- In production, always keep `HORIZON_VERIFY_SSL=true` (default).
- Passwords passed to `horizon_login` are typed as `SecretStr` and masked in server-side logs.
- Access and refresh tokens are returned in the login response so you can copy them to your config — treat them as passwords and clear them from the conversation after use.
- The server holds one Horizon session (the token from `HORIZON_ACCESS_TOKEN` or the last `horizon_login`) shared by every client connected to it. For multiple users, run a separate instance per user with its own `HORIZON_ACCESS_TOKEN` and `MCP_API_KEY`, behind a reverse proxy that enforces TLS.
- Destructive operations ask the user to confirm in the MCP client and are refused if the client can't prompt — see [Confirming destructive operations](#confirming-destructive-operations).
- HTTP transport requires `MCP_API_KEY`, binds to `127.0.0.1` by default, and validates `Host`/`Origin` headers against DNS rebinding.
- IDs passed to tools are percent-encoded before being placed in Horizon API paths, so an ID can't redirect a request to a different endpoint.
