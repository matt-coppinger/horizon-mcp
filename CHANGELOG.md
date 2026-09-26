# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/) (while below 1.0, minor versions may
include breaking changes, which are called out below).

## [Unreleased]

## [0.2.0] - 2026-09-26

Security hardening and fixes found by testing against a live Horizon 2606 server.

### Breaking
- **Destructive tools ask the user to confirm in the MCP client** (MCP elicitation) and are refused if the client can't show the prompt. Set `HORIZON_CONFIRMATION=flag` to accept `confirm=True` instead. See the README's "Confirming destructive operations".
- **HTTP transport requires `MCP_API_KEY`** and refuses to start without it (override with `MCP_ALLOW_UNAUTHENTICATED=true`). It now binds to `127.0.0.1` by default (the Docker image still sets `0.0.0.0`).
- `list_image_management` requires `stream_id` for `versions` and `tags`. Horizon always rejected those calls without it.
- An unknown `MCP_TRANSPORT` value now stops the server at startup with a clear message.

### Added
- DNS-rebinding protection for HTTP transport: `Host` and `Origin` header validation, configurable with `MCP_ALLOWED_HOSTS` and `MCP_ALLOWED_ORIGINS`.
- MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) on every tool.
- CI on every pull request: tests on Python 3.11–3.13, ruff, pyright and `pip-audit`.
- Quickstart, Dockerfile, `docker-compose.yml` and `SECURITY.md`.

### Fixed
- `rdsh_farm_action` now does a real get-then-update round trip. Horizon rejected the partial update it used to send.
- `get_desktop_pool`, `list_desktop_pools`, `get_rdsh_farm` and `list_rdsh_farms` use current API versions that return every field their `update_*` tools need.
- `create_desktop_pool` and `create_rdsh_farm` spec shapes, verified live.
- `HORIZON_VERIFY_SSL` was silently ignored by the shared HTTP client.
- `list_network_interface_cards` now requires `base_vm_id` or `vm_template_id`, as the API does.

### Security
- IDs are percent-encoded before being placed in Horizon API paths, and request paths containing dot-segments, `?`, `#` or `\` are rejected.
- `horizon_login`, `horizon_refresh_token` and `horizon_logout` only accept a `base_url` matching `HORIZON_BASE_URL` when it is set.
- Dependency floors for patched versions of `anyio`, `cryptography`, `mcp`, `pydantic-settings`, `starlette` and `python-multipart`.
- `fastmcp` is constrained to `>=3.3.1,<4`, the range the server is tested with.

## [0.1.0] - 2026-07-01

Initial version (never tagged): MCP tools for Horizon inventory, monitoring, configuration, entitlements, Active Directory, vCenter discovery and help desk, plus read-only `horizon://` resources, stdio and HTTP transports, and `MCP_API_KEY` bearer authentication.

[Unreleased]: https://github.com/matt-coppinger/horizon-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/matt-coppinger/horizon-mcp/releases/tag/v0.2.0
