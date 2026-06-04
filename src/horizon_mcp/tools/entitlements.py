"""Entitlement tools: manage user/group access to desktop and application pools."""
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_delete, api_get, api_post, api_put


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_pool_entitlements(
        pool_type: Annotated[Literal["desktop", "application"], "Type of pool"],
        pool_id: Annotated[
            str,
            "Pool ID to retrieve entitlements for. "
            "If omitted, returns entitlements across all pools of the given type.",
        ] = "",
    ) -> dict | list:
        """Get the users and groups entitled to access a pool (or all pools of a type).

        Returns a single pool's entitlements when pool_id is provided, or a list of
        entitlements for all pools when pool_id is omitted.

        Replaces: get_desktop_pool_entitlement, list_desktop_pool_entitlements,
        get_application_pool_entitlement, list_application_pool_entitlements.
        """
        base = f"/entitlements/v1/{'desktop' if pool_type == 'desktop' else 'application'}-pools"
        if pool_id:
            return await api_get(f"{base}/{pool_id}")
        return await api_get(base) or []

    @mcp.tool()
    async def set_pool_entitlements(
        pool_id: Annotated[str, "Pool ID to modify entitlements for"],
        pool_type: Annotated[Literal["desktop", "application"], "Type of pool"],
        action: Annotated[
            Literal["add", "replace", "remove"],
            "add: merge with existing entitlements. "
            "replace: overwrite all existing entitlements with this list. "
            "remove: revoke access for the specified users/groups.",
        ],
        ad_user_or_group_ids: Annotated[
            list[str],
            "AD user or group IDs. Use search_ad_users_or_groups to find IDs.",
        ],
    ) -> dict:
        """Add, replace, or remove entitlements for a desktop or application pool.

        CAUTION: action='replace' removes any existing entitlements not in the provided list.
        CAUTION: action='remove' immediately revokes access for the specified principals.
        Always confirm with the user before using replace or remove.

        Replaces: set_desktop_pool_entitlements, remove_desktop_pool_entitlements,
        set_application_pool_entitlements.
        """
        base = f"/entitlements/v1/{'desktop' if pool_type == 'desktop' else 'application'}-pools"
        spec = [{"id": pool_id, "ad_user_or_group_ids": ad_user_or_group_ids}]
        if action == "add":
            result = await api_post(base, spec)
        elif action == "replace":
            result = await api_put(base, spec)
        else:
            result = await api_delete(base, spec)
        return result or {"success": True, "pool_id": pool_id, "action": action}
