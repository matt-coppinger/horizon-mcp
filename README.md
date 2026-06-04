# Horizon MCP Server

MCP (Model Context Protocol) server for [Omnissa Horizon](https://www.omnissa.com/products/horizon/) VDI management. Exposes the Horizon REST API (version 2512) as MCP tools covering inventory, monitoring, configuration, entitlements, Active Directory, and help desk functions.

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

> **HTTP transport security:** The HTTP endpoint has no built-in authentication. For any non-localhost deployment, place the server behind a reverse proxy (nginx, Caddy, Traefik) that enforces TLS and an auth mechanism such as mutual TLS or a bearer token check. Each user should run a separate server instance with their own token to maintain session isolation.

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
| `validate_connection_server_backup` | Trigger Connection Server backup |

### Entitlements
| Tool | Description |
|---|---|
| `list_pool_entitlements` | All entitlements for desktop or application pools |
| `get_pool_entitlement` | Users/groups for a specific pool |
| `set_pool_entitlements` | Add, replace, or remove entitlements (desktop or application) |

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
