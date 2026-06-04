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
        base = f"/entitlements/v1/{'desktop' if pool_type == 'desktop' else 'application'}-pools"
        return await api_get(base) or []

    @mcp.tool()
    async def get_pool_entitlement(
        pool_id: Annotated[str, "Pool ID to retrieve entitlements for"],
        pool_type: Annotated[Literal["desktop", "application"], "Type of pool"],
    ) -> dict:
        """Get the users and groups entitled to access a specific pool."""
        base = f"/entitlements/v1/{'desktop' if pool_type == 'desktop' else 'application'}-pools"
        return await api_get(f"{base}/{pool_id}")

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
