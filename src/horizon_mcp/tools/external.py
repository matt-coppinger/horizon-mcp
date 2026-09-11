"""External tools: AD user/group search, domains, audit events, vCenter resources."""
from typing import Annotated

from fastmcp import FastMCP

from ..client import api_get
from ._annotations import READ_ONLY


def register(mcp: FastMCP) -> None:

    # ── Active Directory ───────────────────────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
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

    @mcp.tool(annotations=READ_ONLY)
    async def get_ad_user_or_group(
        ad_id: Annotated[str, "AD user or group ID"],
    ) -> dict:
        """Get detailed information about a specific AD user or group."""
        return await api_get(f"/external/v4/ad-users-or-groups/{ad_id}")

    @mcp.tool(annotations=READ_ONLY)
    async def list_ad_domains() -> list:
        """List all Active Directory domains configured in the Horizon environment.

        Returns domain details including trust relationships, status, and bind accounts.
        """
        return await api_get("/external/v3/ad-domains") or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_ad_containers(
        domain_id: Annotated[str, "AD domain ID — obtain from list_ad_domains"],
    ) -> list:
        """List AD containers (OUs) available in a domain for pool provisioning.

        The rdn (relative distinguished name) from these results is used as the
        ad_container_rdn in create_desktop_pool and create_rdsh_farm provisioning_settings
        to control which OU newly provisioned computers are placed in.
        This is the OU picker equivalent of what the Horizon Console shows during pool creation.
        """
        return await api_get(f"/external/v1/ad-domains/{domain_id}/ad-containers") or []

    @mcp.tool(annotations=READ_ONLY)
    async def get_domain_netbios_map() -> dict:
        """Get a mapping of domain NETBIOS names to DNS names for all configured domains."""
        return await api_get("/external/v1/domains") or {}

    # ── Audit Events ───────────────────────────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
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

    @mcp.tool(annotations=READ_ONLY)
    async def list_base_vms(
        vcenter_id: Annotated[
            str, "vCenter ID to list VMs from. Use list_virtual_centers to get IDs."
        ],
        datacenter_id: Annotated[str, "Datacenter ID to filter by (optional)"] = "",
    ) -> list:
        """List VMs in vCenter that can be used as base images for instant clone pools/farms."""
        params: dict = {}
        if vcenter_id:
            params["vcenter_id"] = vcenter_id
        if datacenter_id:
            params["datacenter_id"] = datacenter_id
        return await api_get("/external/v2/base-vms", params) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_datastores(
        vcenter_id: Annotated[str, "vCenter ID. Use list_virtual_centers to get IDs."],
        host_or_cluster_id: Annotated[
            str, "Host or cluster ID. Use list_hosts_or_clusters to get IDs."
        ],
    ) -> list:
        """List datastores available in vCenter for desktop pool or farm provisioning."""
        params = {"vcenter_id": vcenter_id, "host_or_cluster_id": host_or_cluster_id}
        return await api_get("/external/v1/datastores", params) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_vm_folders(
        vcenter_id: Annotated[str, "vCenter ID"],
        datacenter_id: Annotated[str, "Datacenter ID"],
    ) -> list:
        """List VM folders in a vCenter datacenter for use in pool/farm configuration."""
        params = {"vcenter_id": vcenter_id, "datacenter_id": datacenter_id}
        return await api_get("/external/v1/vm-folders", params) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_datacenters(
        vcenter_id: Annotated[str, "vCenter ID — obtain from list_virtual_centers"],
    ) -> list:
        """List datacenters in a vCenter Server.

        The datacenter ID is required by list_vm_folders, list_hosts_or_clusters,
        and create_desktop_pool / create_rdsh_farm provisioning_settings.
        """
        return await api_get("/external/v1/datacenters", {"vcenter_id": vcenter_id}) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_hosts_or_clusters(
        vcenter_id: Annotated[str, "vCenter ID — obtain from list_virtual_centers"],
        datacenter_id: Annotated[str, "Datacenter ID — obtain from list_datacenters"],
    ) -> list:
        """List hosts and clusters in a vCenter datacenter.

        The host_or_cluster_id is required by list_datastores, list_resource_pools,
        list_network_labels, and create_desktop_pool / create_rdsh_farm provisioning_settings.
        """
        params = {"vcenter_id": vcenter_id, "datacenter_id": datacenter_id}
        return await api_get("/external/v1/hosts-or-clusters", params) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_resource_pools(
        vcenter_id: Annotated[str, "vCenter ID — obtain from list_virtual_centers"],
        host_or_cluster_id: Annotated[
            str, "Host or cluster ID — obtain from list_hosts_or_clusters"
        ],
    ) -> list:
        """List resource pools on a host or cluster.

        The resource_pool_id is required by create_desktop_pool and create_rdsh_farm
        provisioning_settings.
        """
        params = {"vcenter_id": vcenter_id, "host_or_cluster_id": host_or_cluster_id}
        return await api_get("/external/v1/resource-pools", params) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_base_vm_snapshots(
        vcenter_id: Annotated[str, "vCenter ID — obtain from list_virtual_centers"],
        base_vm_id: Annotated[str, "Base VM ID — obtain from list_base_vms"],
    ) -> list:
        """List snapshots of a base VM that can be used as the image for an instant clone pool or farm.

        The snapshot_id is required by create_desktop_pool and create_rdsh_farm
        provisioning_settings when source is INSTANT_CLONE.
        """
        params = {"vcenter_id": vcenter_id, "base_vm_id": base_vm_id}
        return await api_get("/external/v2/base-snapshots", params) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_network_labels(
        vcenter_id: Annotated[str, "vCenter ID — obtain from list_virtual_centers"],
        host_or_cluster_id: Annotated[
            str, "Host or cluster ID — obtain from list_hosts_or_clusters"
        ],
    ) -> list:
        """List network labels (port groups / distributed port groups) available on a host or cluster.

        Network label IDs are used in the nics array of create_desktop_pool and
        create_rdsh_farm provisioning_settings:
          "nics": [{"nic_id": "<id from list_network_interface_cards>", "network_label_id": "<id>"}]
        """
        params = {"vcenter_id": vcenter_id, "host_or_cluster_id": host_or_cluster_id}
        return await api_get("/external/v1/network-labels", params) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_network_interface_cards(
        vcenter_id: Annotated[str, "vCenter ID — obtain from list_virtual_centers"],
        base_vm_id: Annotated[str, "Base VM ID — obtain from list_base_vms (optional)"] = "",
        base_snapshot_id: Annotated[str, "Base snapshot ID — obtain from list_base_vm_snapshots (optional)"] = "",
        vm_template_id: Annotated[str, "VM template ID — obtain from list_vm_templates (optional)"] = "",
    ) -> list:
        """List network interface cards (NICs) available for pool or farm NIC configuration.

        The nic_id from these results pairs with a network_label_id (from list_network_labels)
        in the nics array of create_desktop_pool and create_rdsh_farm provisioning_settings:
          "nics": [{"nic_id": "<id>", "network_label_id": "<id from list_network_labels>"}]

        Pass base_vm_id + base_snapshot_id to filter NICs for an instant-clone pool,
        or vm_template_id to filter NICs for a full/linked-clone pool.
        """
        params: dict = {"vcenter_id": vcenter_id}
        if base_vm_id:
            params["base_vm_id"] = base_vm_id
        if base_snapshot_id:
            params["base_snapshot_id"] = base_snapshot_id
        if vm_template_id:
            params["vm_template_id"] = vm_template_id
        return await api_get("/external/v1/network-interface-cards", params) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_vm_templates(
        vcenter_id: Annotated[str, "vCenter ID — obtain from list_virtual_centers"],
        datacenter_id: Annotated[str, "Datacenter ID — obtain from list_datacenters (optional)"] = "",
    ) -> list:
        """List VM templates available in vCenter for use as pool base images.

        Templates are used for full-clone or linked-clone desktop pools
        (source=FULL_CLONE or LINKED_CLONE). Use the template_id in
        create_desktop_pool provisioning_settings instead of parent_vm_id.
        """
        params: dict = {"vcenter_id": vcenter_id}
        if datacenter_id:
            params["datacenter_id"] = datacenter_id
        return await api_get("/external/v1/vm-templates", params) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_datastore_clusters(
        vcenter_id: Annotated[str, "vCenter ID — obtain from list_virtual_centers"],
        host_or_cluster_id: Annotated[
            str, "Host or cluster ID — obtain from list_hosts_or_clusters"
        ],
    ) -> list:
        """List datastore clusters (Storage DRS pods) available on a host or cluster.

        Use the datastore_cluster_id in create_desktop_pool or create_rdsh_farm
        provisioning_settings when using Storage DRS for automated datastore placement.
        """
        params = {"vcenter_id": vcenter_id, "host_or_cluster_id": host_or_cluster_id}
        return await api_get("/external/v1/datastore-clusters", params) or []

    @mcp.tool(annotations=READ_ONLY)
    async def list_customization_specifications(
        vcenter_id: Annotated[str, "vCenter ID — obtain from list_virtual_centers"],
    ) -> list:
        """List vCenter customization specifications (Sysprep/QuickPrep) available for pool provisioning.

        The customization_specification_id from these results is used in
        create_desktop_pool and create_rdsh_farm provisioning_settings to apply
        OS customization (hostname, domain join, license key) to provisioned VMs.
        """
        return await api_get("/external/v1/customization-specifications", {"vcenter_id": vcenter_id}) or []
