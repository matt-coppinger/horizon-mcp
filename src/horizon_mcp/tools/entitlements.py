"""Entitlement tools: manage user/group access to desktop and application pools."""
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_delete, api_get, api_post, api_put


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def list_pool_entitlements(
        pool_type: Annotated[Literal["desktop", "application"], "Type of pool"],
    ) -> list:
        """List entitlements for all pools of the given type.

        Returns which users and groups are entitled to each pool.
        Use get_pool_entitlement for a specific pool's details.
        """
        return await api_get(f"/entitlements/v1/{pool_type}-pools") or []

    @mcp.tool()
    async def get_pool_entitlement(
        pool_id: Annotated[str, "Pool ID to retrieve entitlements for"],
        pool_type: Annotated[Literal["desktop", "application"], "Type of pool"],
    ) -> dict:
        """Get the users and groups entitled to access a specific pool."""
        return await api_get(f"/entitlements/v1/{pool_type}-pools/{pool_id}")

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

        NOTE: action='replace' is only supported for desktop pools — the Horizon API has
        no bulk-replace endpoint for application pools.
        """
        if action == "replace" and pool_type == "application":
            raise ValueError(
                "action='replace' is not supported for application pools — the Horizon "
                "API has no PUT endpoint for /entitlements/v1/application-pools. Call "
                "get_pool_entitlement first to see current entitlements, then use "
                "action='remove' for principals to revoke and action='add' for principals "
                "to grant."
            )
        if action == "replace" and not ad_user_or_group_ids:
            raise ValueError(
                "action='replace' with an empty list would remove ALL entitlements from "
                "the pool, immediately blocking all user access. Use action='remove' with "
                "an explicit list of principals to revoke, or provide at least one "
                "ad_user_or_group_id."
            )
        spec = [{"id": pool_id, "ad_user_or_group_ids": ad_user_or_group_ids}]
        if action == "add":
            result = await api_post(f"/entitlements/v1/{pool_type}-pools", spec)
        elif action == "replace":
            result = await api_put(f"/entitlements/v1/{pool_type}-pools", spec)
        else:
            result = await api_delete(f"/entitlements/v1/{pool_type}-pools", spec)
        return result or {"success": True, "pool_id": pool_id, "action": action}
