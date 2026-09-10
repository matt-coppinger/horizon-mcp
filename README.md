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
2. **Register the server** — add this to `~/.claude/settings.json` (see [Configuration](#configuration) below for what each variable means):
   ```json
   {
     "mcpServers": {
       "horizon": {
         "command": "uv",
         "args": ["run", "--project", "/absolute/path/to/horizon-mcp", "horizon-mcp"],
         "env": {
           "HORIZON_BASE_URL": "https://horizon.corp.example.com"
         }
       }
     }
   }
   ```
   Use the absolute path to where you cloned the repo. Omit `HORIZON_ACCESS_TOKEN` for now — you'll get one in the next step.
3. **Restart Claude Code**, then get a token by asking it to call `horizon_login` (see [Getting an Access Token](#getting-an-access-token)) with your AD credentials.
4. **Verify it works** — ask Claude Code to call `list_desktop_pools` or `get_infrastructure_health`. If you get real data back, you're set. Copy the `access_token` from step 3 into `HORIZON_ACCESS_TOKEN` in your config so you don't have to log in again on restart.

Running the server standalone over HTTP instead (for remote/multi-user access, or in Docker)? See [HTTP (remote / multi-user)](#http-remote--multi-user) and [Docker](#docker).

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
| `MCP_TRANSPORT` | No | `stdio` (default), `streamable-http`, or `sse` |
| `MCP_HOST` | No | Bind host for HTTP transport (default `0.0.0.0`) |
| `MCP_PORT` | No | Port for HTTP transport (default `8000`) |
| `MCP_API_KEY` | No | HTTP transport only — clients must send `Authorization: Bearer <value>` |

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

**Claude Code** (`~/.claude/settings.json`):
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

### HTTP (remote / multi-user)

```bash
MCP_TRANSPORT=streamable-http \
MCP_PORT=8000 \
HORIZON_BASE_URL=https://horizon.corp.example.com \
HORIZON_ACCESS_TOKEN=your-token \
horizon-mcp
```

The server exposes a single endpoint at `http://host:8000/mcp`.

Set `MCP_API_KEY` to require clients to authenticate with `Authorization: Bearer <MCP_API_KEY>`:

```bash
MCP_TRANSPORT=streamable-http \
MCP_PORT=8000 \
MCP_API_KEY=your-secret-key \
HORIZON_BASE_URL=https://horizon.corp.example.com \
HORIZON_ACCESS_TOKEN=your-token \
horizon-mcp
```

Clients (Claude Desktop, Claude Code) pass the key in their MCP config:

```json
{
  "mcpServers": {
    "horizon": {
      "url": "http://your-server:8000/mcp",
      "headers": {
        "Authorization": "Bearer your-secret-key"
      }
    }
  }
}
```

stdio transport always skips authentication regardless of `MCP_API_KEY`.

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

`MCP_API_KEY` is required by `docker-compose.yml` on purpose — a containerized deployment is reachable over the network by definition, so leaving the endpoint unauthenticated is not a safe default (see [Security Notes](#security-notes)). Point your MCP client at `http://host:8000/mcp` with the matching `Authorization: Bearer` header as shown above.

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

### Auth
| Tool | Description |
|---|---|
| `horizon_login` | Authenticate with AD credentials (password masked in logs), returns access + refresh tokens |
| `horizon_refresh_token` | Refresh an expired access token |
| `horizon_logout` | Invalidate current session |

### Inventory
| Tool | Description |
|---|---|
| `list_desktop_pools` | List all VDI and RDS desktop pools |
| `get_desktop_pool` | Get pool details |
| `create_desktop_pool` | Create a new desktop pool (VDI or RDS, automated or manual) |
| `update_desktop_pool` | Update an existing desktop pool's configuration |
| `delete_desktop_pool` | Delete a desktop pool and all its machines ⚠️ — requires `confirm=True` |
| `desktop_pool_action` | Enable/disable a pool, or enable/disable-provisioning |
| `list_machines` | List virtual desktops (filterable by pool, state) |
| `get_machine` | Get machine details |
| `machine_action` | Shutdown, restart, reset, rebuild, recover, maintenance |
| `assign_machine_users` | Assign or unassign users to a dedicated (non-floating) desktop |
| `list_rdsh_farms` | List RDS farms |
| `get_rdsh_farm` | Get farm details |
| `create_rdsh_farm` | Create a new RDS farm (automated or manual) |
| `update_rdsh_farm` | Update an existing RDS farm's configuration |
| `delete_rdsh_farm` | Delete an RDS farm and all its servers ⚠️ — requires `confirm=True` |
| `rdsh_farm_action` | Enable or disable one or more RDS farms |
| `list_application_pools` | List published application pools |
| `get_application_pool` | Get application pool details |
| `create_application_pool` | Publish a new application pool from an RDS farm |
| `update_application_pool` | Update an existing application pool's configuration |
| `delete_application_pool` | Unpublish an application pool ⚠️ — requires `confirm=True` |
| `list_sessions` | List active user sessions |
| `get_session` | Get session details |
| `disconnect_sessions` | Disconnect sessions (keep running) |
| `logoff_sessions` | Log off sessions (terminates apps) |
| `reset_or_restart_sessions` | Hard-reset or gracefully restart the VMs backing sessions |
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
| `get_global_policies` | USB, clipboard, multimedia policies |
| `list_licenses` | License list and status |
| `get_event_database` | Event DB config |
| `list_ic_domain_accounts` | Instant clone domain accounts |
| `list_image_management` | Image management streams, versions, or tags (pass `resource`: `streams`\|`versions`\|`tags`) |
| `list_gateways` | Registered UAGs |
| `trigger_connection_server_backup` | Trigger Connection Server backup |

### Entitlements
| Tool | Description |
|---|---|
| `list_pool_entitlements` | All entitlements for desktop or application pools |
| `get_pool_entitlement` | Users/groups for a specific pool |
| `set_pool_entitlements` | Add, replace, or remove entitlements (desktop or application) — `replace` is desktop-pool only, the Horizon API has no bulk-replace endpoint for application pools |

### External / Active Directory
| Tool | Description |
|---|---|
| `search_ad_users_or_groups` | Find AD users and groups |
| `get_ad_user_or_group` | Get AD entity details |
| `list_ad_domains` | List configured AD domains |
| `get_domain_netbios_map` | NETBIOS → DNS domain name map |
| `list_audit_events` | Administrative audit log |
| `list_base_vms` | VMs available for pool base images |
| `list_base_vm_snapshots` | Snapshots of a base VM (snapshot_id for instant clone pools) |
| `list_datastores` | Datastores for provisioning (requires vcenter_id + host_or_cluster_id) |
| `list_vm_folders` | VM folders in vCenter |
| `list_datacenters` | Datacenters in a vCenter Server |
| `list_hosts_or_clusters` | Hosts and clusters in a datacenter |
| `list_resource_pools` | Resource pools on a host or cluster |
| `list_network_labels` | Network port groups on a host or cluster |
| `list_network_interface_cards` | NICs on a host or cluster (nic_id for pool NIC config) |
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
| `end_remote_application` | Force-close a published app in a session |

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

## Creating Pools and Farms

`create_desktop_pool` and `create_rdsh_farm` accept a `spec` dict that maps directly to the Horizon REST API request body. The required fields vary by pool type:

**Automated Instant Clone desktop pool (minimum):**
```json
{
  "name": "MyPool",
  "display_name": "My Pool",
  "type": "AUTOMATED",
  "source": "INSTANT_CLONE",
  "user_assignment": "FLOATING",
  "provisioning_settings": {
    "virtual_center_id": "<id from list_virtual_centers>",
    "parent_vm_id": "<id from list_base_vms>",
    "snapshot_id": "<snapshot id>",
    "datacenter_id": "<datacenter id>",
    "vm_folder_id": "<id from list_vm_folders>",
    "host_or_cluster_id": "<host/cluster id>",
    "resource_pool_id": "<resource pool id>",
    "datastores": [{"datastore_id": "<id from list_datastores>"}],
    "nics": [{"nic_id": "<network id>", "network_label_id": "<network id>"}],
    "naming_method": "PATTERN",
    "naming_pattern": "MyPool-{n:fixed=2}",
    "max_machine_count": 10
  }
}
```

**Resource ID lookup chain** — follow this sequence to resolve all IDs before calling `create_desktop_pool` or `create_rdsh_farm`:

```
list_virtual_centers
  ├─ list_customization_specifications(vcenter_id)   ← Sysprep/QuickPrep spec ID
  ├─ list_vm_templates(vcenter_id)                   ← template_id (full/linked-clone pools)
  └─ list_datacenters(vcenter_id)
       ├─ list_vm_folders(vcenter_id, datacenter_id)
       └─ list_hosts_or_clusters(vcenter_id, datacenter_id)
            ├─ list_datastores(vcenter_id, host_or_cluster_id)
            ├─ list_datastore_clusters(vcenter_id, host_or_cluster_id)
            ├─ list_resource_pools(vcenter_id, host_or_cluster_id)
            ├─ list_network_labels(vcenter_id, host_or_cluster_id)  ← network_label_id
            └─ list_network_interface_cards(vcenter_id, ...)        ← nic_id
list_base_vms(vcenter_id)                            ← parent_vm_id (instant-clone pools)
  └─ list_base_vm_snapshots(vcenter_id, base_vm_id)  ← snapshot_id
```

`create_application_pool` uses explicit parameters instead — pass `name`, `farm_id`, `executable_path`, and optional fields directly.

For updates, retrieve the current config with `get_desktop_pool` / `get_rdsh_farm` / `get_application_pool`, modify the relevant fields, and pass the result to the corresponding `update_*` tool.

**Delete operations** (`delete_desktop_pool`, `delete_rdsh_farm`, `delete_application_pool`) require `confirm=True` to proceed. Always call `get_desktop_pool` / `get_rdsh_farm` and `list_sessions` first to verify intent before passing `confirm=True`.

## Running Tests

```bash
uv run pytest tests/ -v
```

## Security Notes

- Store credentials in your MCP client's `env` block, not in code or config files tracked by git.
- In production, always keep `HORIZON_VERIFY_SSL=true` (default).
- Passwords passed to `horizon_login` are typed as `SecretStr` and masked in server-side logs.
- Access and refresh tokens are returned in the login response so you can copy them to your config — treat them as passwords and clear them from the conversation after use.
- For multi-user HTTP deployments, run separate server instances per user and protect the endpoint with a reverse proxy that enforces authentication.
- Destructive operations (logoff, rebuild, machine actions) require explicit user confirmation — always verify intent before executing.
