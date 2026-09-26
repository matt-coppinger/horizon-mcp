"""Config tools: connection servers, virtual centers, licenses, settings, policies."""
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_get, api_post, api_put, seg
from ._annotations import ADDITIVE, DESTRUCTIVE_UPDATE, READ_ONLY
from ._confirm import require_confirmation
from ._results import bulk_result


async def _describe_changes(path: str, spec: dict) -> str:
    """List the top-level fields `spec` would change, for a confirmation prompt."""
    try:
        current = await api_get(path) or {}
    except Exception:
        return f"fields: {', '.join(sorted(spec)) or '(none)'}"
    changed = [
        f"{k}: {current.get(k)!r} → {v!r}" for k, v in sorted(spec.items()) if current.get(k) != v
    ]
    if not changed:
        return "no fields differ from the current values"
    more = f" (+{len(changed) - 8} more)" if len(changed) > 8 else ""
    return "; ".join(changed[:8]) + more


def register(mcp: FastMCP) -> None:

    # ── Connection Servers ─────────────────────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
    async def list_connection_servers() -> list:
        """List all Horizon Connection Servers in the pod."""
        return await api_get("/config/v1/connection-servers") or []

    @mcp.tool(annotations=READ_ONLY)
    async def get_connection_server(
        server_id: Annotated[str, "Connection server ID"],
    ) -> dict:
        """Get configuration details for a specific Connection Server."""
        return await api_get(f"/config/v1/connection-servers/{seg(server_id)}")

    # ── Virtual Centers ────────────────────────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
    async def list_virtual_centers() -> list:
        """List all vCenter Servers configured in the Horizon environment."""
        return await api_get("/config/v6/virtual-centers") or []

    # ── Environment & Settings ─────────────────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
    async def get_environment_properties() -> dict:
        """Get environment-level properties including version, FIPS mode, and feature flags."""
        return await api_get("/config/v3/environment-properties")

    @mcp.tool(annotations=READ_ONLY)
    async def get_settings() -> dict:
        """Get the global Horizon configuration settings.

        Includes client session timeouts, pre-launch settings, display protocol
        defaults, HTML Access settings, and other global options.
        """
        return await api_get("/config/v9/settings")

    @mcp.tool(annotations=READ_ONLY)
    async def get_global_policies() -> dict:
        """Get global VDI policies including USB redirection, multimedia redirection,
        clipboard settings, and other environment-wide policy settings."""
        return await api_get("/config/v1/global-policies")

    @mcp.tool(annotations=DESTRUCTIVE_UPDATE)
    async def update_global_policies(
        spec: Annotated[
            dict,
            "Updated global policies object. Call get_global_policies first, modify only the "
            "fields you intend to change, then pass the full object here.",
        ],
        confirm: Annotated[
            bool,
            "Only used when the server runs with HORIZON_CONFIRMATION=flag (clients without "
            "elicitation). Otherwise the user is asked to confirm directly in the client.",
        ] = False,
    ) -> dict:
        """Update global VDI policies (USB redirection, clipboard, multimedia redirection).

        Always call get_global_policies first to read current values.
        Only modify the specific fields you intend to change — pass the full object back.
        """
        changes = await _describe_changes("/config/v1/global-policies", spec)
        await require_confirmation(f"Change Horizon global policies — {changes}.", confirm=confirm)
        result = await api_put("/config/v1/global-policies", spec)
        return result or {"success": True}

    @mcp.tool(annotations=DESTRUCTIVE_UPDATE)
    async def update_settings(
        setting_type: Annotated[
            Literal["general", "security", "client", "feature", "agent-restriction"],
            "Settings section to update. Read current values via the corresponding "
            "horizon://config/settings/<type> resource before modifying.",
        ],
        spec: Annotated[
            dict,
            "Updated settings object. Read current values first, modify only the fields "
            "you intend to change, then pass the full object here.",
        ],
        confirm: Annotated[
            bool,
            "Only used when the server runs with HORIZON_CONFIRMATION=flag (clients without "
            "elicitation). Otherwise the user is asked to confirm directly in the client.",
        ] = False,
    ) -> dict:
        """Update a Horizon settings section.

        setting_type maps to these resources and endpoints:
          general          → horizon://config/settings/general
          security         → horizon://config/settings/security
          client           → horizon://config/settings/client
          feature          → horizon://config/settings/feature
          agent-restriction → horizon://config/settings/agent-restriction

        Always read the current settings first and only modify the fields you intend to change.
        """
        paths = {
            "general": "/config/v1/settings/general",
            "security": "/config/v1/settings/security",
            "client": "/config/v1/settings/client-settings",
            "feature": "/config/v1/settings/feature",
            "agent-restriction": "/config/v1/settings/agent-restriction-settings",
        }
        changes = await _describe_changes(paths[setting_type], spec)
        await require_confirmation(f"Change Horizon {setting_type} settings — {changes}.", confirm=confirm)
        result = await api_put(paths[setting_type], spec)
        return result or {"success": True, "setting_type": setting_type}

    # ── Licenses ───────────────────────────────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
    async def list_licenses() -> list:
        """List all Horizon licenses and their status, mode, and expiry information."""
        return await api_get("/config/v1/licenses") or []

    # ── Event Database ─────────────────────────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
    async def get_event_database() -> dict:
        """Get the configuration and connection status of the Horizon event database."""
        return await api_get("/config/v1/event-database")

    # ── Instant Clone Domain Accounts ─────────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
    async def list_ic_domain_accounts() -> list:
        """List instant clone domain accounts used for provisioning instant clone desktops."""
        return await api_get("/config/v1/ic-domain-accounts") or []

    # ── Image Management ───────────────────────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
    async def list_image_management(
        resource: Annotated[
            Literal["streams", "versions", "tags"],
            "Image management resource to list: "
            "streams (publishing pipelines), versions (published images), tags (pool targets).",
        ],
        stream_id: Annotated[
            str,
            "Image stream ID — required for versions and tags. Obtain from resource='streams'.",
        ] = "",
    ) -> list:
        """List image management streams, versions, or tags.

        Versions and tags belong to a stream, so Horizon requires a stream ID for them
        (verified live — omitting it returns 400 "im_stream_id parameter is missing").
        List streams first, then pass a stream's id as stream_id.
        """
        paths: dict[str, str] = {
            "streams": "/config/v1/im-streams",
            "versions": "/config/v1/im-versions",
            "tags": "/config/v1/im-tags",
        }
        if resource == "streams":
            return await api_get(paths[resource]) or []
        if not stream_id:
            raise ValueError(
                f"stream_id is required for resource='{resource}'. "
                "Call list_image_management(resource='streams') to get stream IDs."
            )
        return await api_get(paths[resource], {"im_stream_id": stream_id}) or []

    # ── Gateways ───────────────────────────────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
    async def list_gateways() -> list:
        """List all registered Unified Access Gateways."""
        return await api_get("/config/v1/gateways") or []

    @mcp.tool(annotations=ADDITIVE)
    async def trigger_connection_server_backup(
        server_ids: Annotated[
            list[str] | None,
            "Connection server IDs to back up. If omitted, all Connection Servers are backed up.",
        ] = None,
    ) -> dict:
        """Initiate an immediate backup of one or more Connection Servers.

        CAUTION: This triggers an active backup operation, not a validation check.
        If no server_ids are provided, all Connection Servers are backed up.
        """
        result = await api_post("/config/v1/connection-servers/action/backup", server_ids or [])
        return bulk_result(result)
