# Horizon MCP Server

MCP (Model Context Protocol) server for [Omnissa Horizon](https://www.omnissa.com/products/horizon/) VDI management. Exposes the Horizon REST API (version 2512) as 66 MCP tools covering inventory, monitoring, configuration, entitlements, Active Directory, and help desk functions.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Horizon Connection Server 2512 or later

## Installation

```bash
# Clone and install
git clone <repo-url>
cd HorizonMCP
uv venv && uv pip install -e .
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

**Claude Code** (`.claude/settings.json` in your project, or `~/.claude/settings.json` globally):
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

## Getting an Access Token

If you don't have a token yet, omit `HORIZON_ACCESS_TOKEN` from the config and call `horizon_login` as the first tool:

```
Call horizon_login with:
  username: jsmith
  password: ******
  domain: CORP
  base_url: https://horizon.corp.example.com
```

The tool returns `access_token` and `refresh_token`, and immediately activates the new token for the current server session. Copy the `access_token` value into your MCP client config and restart the server to persist it across restarts.

Use `horizon_refresh_token` with the `refresh_token` to renew the access token (~8 hour expiry) without re-entering credentials.

## Available Tools

### Auth
| Tool | Description |
|---|---|
| `horizon_login` | Authenticate with AD credentials, returns access + refresh tokens |
| `horizon_refresh_token` | Refresh an expired access token |
| `horizon_logout` | Invalidate current session |

### Inventory
| Tool | Description |
|---|---|
| `list_desktop_pools` | List all VDI and RDS desktop pools |
| `get_desktop_pool` | Get pool details |
| `list_machines` | List virtual desktops (filterable by pool, state) |
| `get_machine` | Get machine details |
| `machine_action` | Shutdown, restart, reset, rebuild, recover, maintenance |
| `list_rdsh_farms` | List RDS farms |
| `get_rdsh_farm` | Get farm details |
| `list_application_pools` | List published application pools |
| `get_application_pool` | Get application pool details |
| `list_sessions` | List active user sessions |
| `get_session` | Get session details |
| `disconnect_sessions` | Disconnect sessions (keep running) |
| `logoff_sessions` | Log off sessions (terminates apps) |
| `send_message_to_sessions` | Send pop-up notification to sessions |

### Monitor
| Tool | Description |
|---|---|
| `get_health_metrics` | Overall environment health summary |
| `list_connection_servers_health` | Connection server health |
| `get_connection_server_health` | Single connection server health |
| `list_desktop_pool_metrics` | Session/machine counts per pool |
| `get_session_metrics` | Aggregate session counts |
| `list_gateway_health` | UAG health status |
| `list_virtual_center_health` | vCenter health |
| `list_ad_domain_health` | AD domain reachability |
| `get_machine_count_metrics` | Machine state totals |
| `get_system_metrics` | CPU/memory for all components |
| `list_farm_health` | RDS farm health |
| `get_license_usage_metrics` | License usage data |

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
| `list_im_streams` / `list_im_versions` / `list_im_tags` | Image management |
| `list_gateways` | Registered UAGs |

### Entitlements
| Tool | Description |
|---|---|
| `list_desktop_pool_entitlements` | All desktop pool entitlements |
| `get_desktop_pool_entitlement` | Users/groups for a pool |
| `set_desktop_pool_entitlements` | Add or replace entitlements |
| `remove_desktop_pool_entitlements` | Remove entitlements |
| `list_application_pool_entitlements` | All app pool entitlements |
| `get_application_pool_entitlement` | Users/groups for an app pool |
| `set_application_pool_entitlements` | Add or replace app entitlements |

### External / Active Directory
| Tool | Description |
|---|---|
| `search_ad_users_or_groups` | Find AD users and groups |
| `get_ad_user_or_group` | Get AD entity details |
| `list_ad_domains` | List configured AD domains |
| `get_domain_netbios_map` | NETBIOS → DNS domain name map |
| `list_audit_events` | Administrative audit log |
| `list_base_vms` | VMs available for pool base images |
| `list_datastores` | Datastores for provisioning |
| `list_vm_folders` | VM folders in vCenter |

### Help Desk
| Tool | Description |
|---|---|
| `get_session_logon_timing` | Detailed logon phase timing |
| `get_session_display_performance` | Real-time PCoIP/BLAST metrics |
| `get_session_historical_performance` | 15-minute performance history |
| `get_session_processes` | Processes running in session |
| `get_remote_assistance_ticket` | MSRA ticket for remote support |
| `get_session_remote_applications` | Running published apps |
| `end_remote_application` | Force-close a published app |

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

## Security Notes

- Store credentials in your MCP client's `env` block, not in code or config files tracked by git.
- In production, always keep `HORIZON_VERIFY_SSL=true` (default).
- The access token is transmitted in the `Authorization: Bearer` header to the Horizon server. Ensure your network path uses TLS.
- This server stores the active token in the process environment. For multi-user HTTP deployments, consider running separate server instances per user.
- Destructive operations (logoff, rebuild, machine actions) require explicit confirmation — always verify before executing.
