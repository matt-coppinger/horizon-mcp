# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/) (while below 1.0, minor versions may
include breaking changes, which are called out below).

## [Unreleased]

### Breaking
- `horizon_login` and `horizon_refresh_token` return only 8-character token hints; the server keeps the tokens itself. Set `HORIZON_EXPOSE_TOKENS=true` to get the full values back (e.g. to copy into a client config). (#20)
- The seven paginated list tools (`list_desktop_pools`, `list_machines`, `list_rdsh_farms`, `list_application_pools`, `list_sessions`, `search_ad_users_or_groups`, `list_audit_events`) return `{items, count, page, size, pages_fetched, has_more, next_page, truncated}` instead of a bare list. (#21)

### Added
- Automatic token refresh: on HTTP 401 the server refreshes once using the refresh token it holds, then retries the request once. `HORIZON_REFRESH_TOKEN` can seed it at startup, and `horizon_refresh_token` / `horizon_logout` no longer need a token argument. (#20)
- Audit log: one JSON line per confirmation decision, write request (POST/PUT/DELETE) and login/refresh/logout, on stderr or to `HORIZON_AUDIT_LOG`. Request bodies, tokens and passwords are never logged. (#20)
- `has_more` / `next_page` on paginated list results, and an optional `fetch_all` (up to 10 pages / 5,000 items). (#21)
- Opt-in live integration suite in `tests/live/`, driving the server over MCP stdio against a real Horizon lab. It is skipped unless `HZ_*` variables are set. (#22)

### Fixed
- Nine bulk-action tools (`machine_action`, session actions, `desktop_pool_action`, `set_pool_entitlements`, `assign_machine_users`, `send_message_to_sessions`, `trigger_connection_server_backup`) reported an error over MCP even after Horizon had done the work, because Horizon's list response was rejected by the tools' dict return type. They now return `{success, succeeded, failed}`, which also shows partial failures. (#19)
- `create_desktop_pool` and `create_rdsh_farm` raised "may not have been created" on Horizon's documented empty 201 success response. They and `create_application_pool` now look the new item up by name and return its ID. (#19)
- `update_settings` now warns that Horizon rejects its own `general` settings unless every `restricted_client_data` entry has a `version` (verified on 2606).

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
