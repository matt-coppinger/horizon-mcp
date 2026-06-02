"""External tools: AD user/group search, domains, audit events, vCenter resources."""
from typing import Annotated

from fastmcp import FastMCP

from ..client import api_get


def register(mcp: FastMCP) -> None:

    # ── Active Directory ───────────────────────────────────────────────────────

    @mcp.tool()
    async def search_ad_users_or_groups(
        filter: Annotated[
            str,
            'Horizon filter JSON. Example to search by name: '
            '{"type":"Contains","name":"name","value":"john"} '
            'or by login: {"type":"Equals","name":"login_name","value":"jsmith"}',
        ] = "",
        page: Annotated[int, "Page number (1-based)"] = 1,
        size: Annotated[int, "Results per page (max 1000)"] = 50,
    ) -> list:
        """Search for AD users and groups in the Horizon environment.

        Use the returned 'id' field when setting pool entitlements.

        Common filter fields: name, login_name, group, domain.
        Example filters:
          Find user by login: {"type":"Equals","name":"login_name","value":"jsmith"}
          Find by display name: {"type":"Contains","name":"name","value":"John"}
          Groups only: {"type":"Equals","name":"group","value":"true"}
        """
        params: dict = {"page": page, "size": size}
        if filter:
            params["filter"] = filter
        return await api_get("/external/v4/ad-users-or-groups", params) or []

    @mcp.tool()
    async def get_ad_user_or_group(
        ad_id: Annotated[str, "AD user or group ID"],
    ) -> dict:
        """Get detailed information about a specific AD user or group."""
        return await api_get(f"/external/v4/ad-users-or-groups/{ad_id}")

    @mcp.tool()
    async def list_ad_domains() -> list:
        """List all Active Directory domains configured in the Horizon environment.

        Returns domain details including trust relationships, status, and bind accounts.
        """
        return await api_get("/external/v3/ad-domains") or []

    @mcp.tool()
    async def get_domain_netbios_map() -> dict:
        """Get a mapping of domain NETBIOS names to DNS names for all configured domains."""
        return await api_get("/external/v1/domains") or {}

    # ── Audit Events ───────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_audit_events(
        filter: Annotated[
            str,
            "Horizon filter JSON to narrow results by event type, user, or time range",
        ] = "",
        page: Annotated[int, "Page number (1-based)"] = 1,
        size: Annotated[int, "Results per page (max 1000)"] = 100,
    ) -> list:
        """List Horizon audit events (administrative actions and system events).

        Useful for reviewing recent changes, troubleshooting, and compliance auditing.
        """
        params: dict = {"page": page, "size": size}
        if filter:
            params["filter"] = filter
        return await api_get("/external/v2/audit-events", params) or []

    # ── vCenter Resources (for pool/farm provisioning reference) ───────────────

    @mcp.tool()
    async def list_base_vms(
        vcenter_id: Annotated[
            str, "vCenter ID to list VMs from. Use list_virtual_centers to get IDs."
        ] = "",
        datacenter_id: Annotated[str, "Datacenter ID to filter by (optional)"] = "",
    ) -> list:
        """List VMs in vCenter that can be used as base images for instant clone pools/farms."""
        params: dict = {}
        if vcenter_id:
            params["vcenter_id"] = vcenter_id
        if datacenter_id:
            params["datacenter_id"] = datacenter_id
        return await api_get("/external/v2/base-vms", params) or []

    @mcp.tool()
    async def list_datastores(
        vcenter_id: Annotated[str, "vCenter ID. Use list_virtual_centers to get IDs."],
        host_or_cluster_id: Annotated[
            str, "Host or cluster ID. Use list_hosts_or_clusters to get IDs."
        ] = "",
    ) -> list:
        """List datastores available in vCenter for desktop pool or farm provisioning."""
        params: dict = {"vcenter_id": vcenter_id}
        if host_or_cluster_id:
            params["host_or_cluster_id"] = host_or_cluster_id
        return await api_get("/external/v1/datastores", params) or []

    @mcp.tool()
    async def list_vm_folders(
        vcenter_id: Annotated[str, "vCenter ID"],
        datacenter_id: Annotated[str, "Datacenter ID"],
    ) -> list:
        """List VM folders in a vCenter datacenter for use in pool/farm configuration."""
        params = {"vcenter_id": vcenter_id, "datacenter_id": datacenter_id}
        return await api_get("/external/v1/vm-folders", params) or []
