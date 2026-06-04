"""Config tools: connection servers, virtual centers, licenses, settings, policies."""
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_get, api_post


def register(mcp: FastMCP) -> None:

    # ── Connection Servers ─────────────────────────────────────────────────────

    @mcp.tool()
    async def list_connection_servers() -> list:
        """List all Horizon Connection Servers in the pod."""
        return await api_get("/config/v1/connection-servers") or []

    @mcp.tool()
    async def get_connection_server(
        server_id: Annotated[str, "Connection server ID"],
    ) -> dict:
        """Get configuration details for a specific Connection Server."""
        return await api_get(f"/config/v1/connection-servers/{server_id}")

    # ── Virtual Centers ────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_virtual_centers() -> list:
        """List all vCenter Servers configured in the Horizon environment."""
        return await api_get("/config/v6/virtual-centers") or []

    # ── Environment & Settings ─────────────────────────────────────────────────

    @mcp.tool()
    async def get_environment_properties() -> dict:
        """Get environment-level properties including version, FIPS mode, and feature flags."""
        return await api_get("/config/v3/environment-properties")

    @mcp.tool()
    async def get_settings() -> dict:
        """Get the global Horizon configuration settings.

        Includes client session timeouts, pre-launch settings, display protocol
        defaults, HTML Access settings, and other global options.
        """
        return await api_get("/config/v9/settings")

    @mcp.tool()
    async def get_global_policies() -> dict:
        """Get global VDI policies including USB redirection, multimedia redirection,
        clipboard settings, and other environment-wide policy settings."""
        return await api_get("/config/v1/global-policies")

    # ── Licenses ───────────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_licenses() -> list:
        """List all Horizon licenses and their status, mode, and expiry information."""
        return await api_get("/config/v1/licenses") or []

    # ── Event Database ─────────────────────────────────────────────────────────

    @mcp.tool()
    async def get_event_database() -> dict:
        """Get the configuration and connection status of the Horizon event database."""
        return await api_get("/config/v1/event-database")

    # ── Instant Clone Domain Accounts ─────────────────────────────────────────

    @mcp.tool()
    async def list_ic_domain_accounts() -> list:
        """List instant clone domain accounts used for provisioning instant clone desktops."""
        return await api_get("/config/v1/ic-domain-accounts") or []

    # ── Image Management ───────────────────────────────────────────────────────

    @mcp.tool()
    async def list_image_management(
        resource: Annotated[
            Literal["streams", "versions", "tags"],
            "Image management resource to list: "
            "streams (publishing pipelines), versions (published images), tags (pool targets).",
        ],
    ) -> list:
        """List image management streams, versions, or tags.

        Replaces: list_im_streams, list_im_versions, list_im_tags.
        """
        paths = {
            "streams": "/config/v1/im-streams",
            "versions": "/config/v1/im-versions",
            "tags": "/config/v1/im-tags",
        }
        return await api_get(paths[resource]) or []

    # ── Gateways ───────────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_gateways() -> list:
        """List all registered Unified Access Gateways."""
        return await api_get("/config/v1/gateways") or []

    @mcp.tool()
    async def validate_connection_server_backup(
        server_ids: Annotated[
            list[str] | None,
            "Connection server IDs to back up. If omitted, all Connection Servers are backed up.",
        ] = None,
    ) -> dict:
        """Initiate an immediate backup of one or more Connection Servers."""
        result = await api_post("/config/v1/connection-servers/action/backup", server_ids or [])
        return result or {"success": True}
