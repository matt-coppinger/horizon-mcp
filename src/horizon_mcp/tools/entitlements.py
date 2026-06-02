"""Entitlement tools: manage user/group access to desktop and application pools."""
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_delete, api_get, api_post, api_put


def register(mcp: FastMCP) -> None:

    # ── Desktop Pool Entitlements ──────────────────────────────────────────────

    @mcp.tool()
    async def list_desktop_pool_entitlements() -> list:
        """List all desktop pool entitlements (which users/groups can access which pools)."""
        return await api_get("/entitlements/v1/desktop-pools") or []

    @mcp.tool()
    async def get_desktop_pool_entitlement(
        pool_id: Annotated[str, "Desktop pool ID"],
    ) -> dict:
        """Get the list of users and groups entitled to access a specific desktop pool."""
        return await api_get(f"/entitlements/v1/desktop-pools/{pool_id}")

    @mcp.tool()
    async def set_desktop_pool_entitlements(
        pool_id: Annotated[str, "Desktop pool ID"],
        ad_user_or_group_ids: Annotated[
            list[str],
            "AD user or group IDs to entitle. Use search_ad_users_or_groups to find IDs.",
        ],
        operation: Annotated[
            Literal["add", "replace"],
            "add: merge with existing entitlements; replace: overwrite all existing entitlements",
        ] = "add",
    ) -> dict:
        """Add or replace entitlements for a desktop pool.

        Use search_ad_users_or_groups to look up AD user/group IDs before calling this.
        CAUTION: Using operation='replace' will remove any existing entitlements not in the list.
        """
        spec = [{"id": pool_id, "ad_user_or_group_ids": ad_user_or_group_ids}]
        if operation == "add":
            result = await api_post("/entitlements/v1/desktop-pools", spec)
        else:
            result = await api_put("/entitlements/v1/desktop-pools", spec)
        return result or {"success": True, "pool_id": pool_id}

    @mcp.tool()
    async def remove_desktop_pool_entitlements(
        pool_id: Annotated[str, "Desktop pool ID"],
        ad_user_or_group_ids: Annotated[
            list[str],
            "AD user or group IDs to remove from entitlements",
        ],
    ) -> dict:
        """Remove specific users or groups from a desktop pool's entitlements.

        CAUTION: Removing entitlements will prevent those users from connecting to the pool.
        """
        spec = [{"id": pool_id, "ad_user_or_group_ids": ad_user_or_group_ids}]
        result = await api_delete("/entitlements/v1/desktop-pools", spec)
        return result or {"success": True, "pool_id": pool_id}

    # ── Application Pool Entitlements ──────────────────────────────────────────

    @mcp.tool()
    async def list_application_pool_entitlements() -> list:
        """List all application pool entitlements."""
        return await api_get("/entitlements/v1/application-pools") or []

    @mcp.tool()
    async def get_application_pool_entitlement(
        pool_id: Annotated[str, "Application pool ID"],
    ) -> dict:
        """Get the list of users and groups entitled to access a specific application pool."""
        return await api_get(f"/entitlements/v1/application-pools/{pool_id}")

    @mcp.tool()
    async def set_application_pool_entitlements(
        pool_id: Annotated[str, "Application pool ID"],
        ad_user_or_group_ids: Annotated[
            list[str],
            "AD user or group IDs to entitle",
        ],
        operation: Annotated[
            Literal["add", "replace"],
            "add: merge with existing entitlements; replace: overwrite all existing entitlements",
        ] = "add",
    ) -> dict:
        """Add or replace entitlements for an application pool."""
        spec = [{"id": pool_id, "ad_user_or_group_ids": ad_user_or_group_ids}]
        if operation == "add":
            result = await api_post("/entitlements/v1/application-pools", spec)
        else:
            result = await api_put("/entitlements/v1/application-pools", spec)
        return result or {"success": True, "pool_id": pool_id}
