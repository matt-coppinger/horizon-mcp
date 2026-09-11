"""Config tools: connection servers, virtual centers, licenses, settings, policies."""
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_get, api_post, api_put
from ._annotations import ADDITIVE, IDEMPOTENT_UPDATE, READ_ONLY


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
        return await api_get(f"/config/v1/connection-servers/{server_id}")

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

    @mcp.tool(annotations=IDEMPOTENT_UPDATE)
    async def update_global_policies(
        spec: Annotated[
            dict,
            "Updated global policies object. Call get_global_policies first, modify only the "
            "fields you intend to change, then pass the full object here.",
        ],
    ) -> dict:
        """Update global VDI policies (USB redirection, clipboard, multimedia redirection).

        Always call get_global_policies first to read current values.
        Only modify the specific fields you intend to change — pass the full object back.
        """
        result = await api_put("/config/v1/global-policies", spec)
        return result or {"success": True}

    @mcp.tool(annotations=IDEMPOTENT_UPDATE)
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
    ) -> list:
        """List image management streams, versions, or tags.

        """
        paths: dict[str, str] = {
            "streams": "/config/v1/im-streams",
            "versions": "/config/v1/im-versions",
            "tags": "/config/v1/im-tags",
        }
        return await api_get(paths[resource]) or []

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
        return result or {"success": True}
