"""Resolve vCenter placement from HZ_* env vars and build create specs for test pools/farms.

Shared by test_destructive.py (throwaway farm) and the end-to-end lifecycle test (farm and
desktop pool). Every value is looked up through the server's own list tools, by name or
ID from the env, falling back to the first entry listed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .harness import LiveToolError, Session, pick
from .sweep import find_host_or_cluster

# Properties ApplicationPoolUpdateSpec accepts (Horizon 2606 swagger). get_application_pool
# returns more (id, name, farm_id, icon_ids, ...) that the PUT doesn't take.
APP_POOL_UPDATE_FIELDS = {
    "anti_affinity_data", "category_folder_name", "cs_restriction_tags", "description", "display_name",
    "enable_client_restrictions", "enable_pre_launch", "enabled", "executable_path", "max_multi_sessions",
    "multi_session_mode", "parameters", "publisher", "shortcut_locations", "start_folder",
    "supported_file_types_data", "version",
}

# Fields update_desktop_pool's description says to strip from get_desktop_pool's response.
POOL_READ_ONLY_FIELDS = {
    "id", "name", "type", "source", "naming_method", "vcenter_id", "vcenter_name", "farm_id",
    "user_assignment", "created_at", "updated_at", "delete_in_progress", "num_machines", "num_sessions",
    "num_application_sessions", "user_group_count", "application_count",
}


def _need(value, what: str):
    if not value:
        raise LiveToolError(f"Could not resolve {what} — set the matching HZ_* override")
    return value


@dataclass
class Placement:
    vcenter_id: str
    datacenter_id: str
    host_or_cluster_id: str
    resource_pool_id: str
    vm_folder_id: str
    datastore_id: str
    parent_vm_id: str
    base_snapshot_id: str
    access_group_id: str
    ic_domain_account_id: str
    ad_container_rdn: str | None


async def resolve_placement(s: Session, *, base_vm_env: str, snapshot_env: str) -> Placement:
    """Look up every ID a create spec needs. base_vm_env / snapshot_env name the env vars
    holding the base VM and snapshot (name or ID) — the one choice that must be explicit."""
    vc = _need(pick(await s.call("list_virtual_centers"), "HZ_VCENTER"), "a vCenter")
    v = {"vcenter_id": vc["id"]}
    dc = _need(pick(await s.call("list_datacenters", v), "HZ_DATACENTER"), "a datacenter")
    hc = _need(find_host_or_cluster(await s.call("list_hosts_or_clusters", {**v, "datacenter_id": dc["id"]}),
                                    os.environ.get("HZ_CLUSTER")), "a host or cluster")
    hcv = {**v, "host_or_cluster_id": hc["id"]}
    rp = _need(pick(await s.call("list_resource_pools", hcv), "HZ_RESOURCE_POOL"), "a resource pool")
    folder = _need(pick(await s.call("list_vm_folders", {**v, "datacenter_id": dc["id"]}), "HZ_VM_FOLDER"),
                   "a VM folder")
    ds = _need(pick(await s.call("list_datastores", hcv), "HZ_DATASTORE"), "a datastore")
    vm = _need(pick(await s.call("list_base_vms", v), base_vm_env), base_vm_env)
    snap = _need(pick(await s.call("list_base_vm_snapshots", {**v, "base_vm_id": vm["id"]}), snapshot_env),
                 f"{snapshot_env} on that base VM")
    ag = _need(pick(await s.read_json_resource("horizon://config/local-access-groups"), "HZ_ACCESS_GROUP"),
               "an access group")
    ic = _need(pick(await s.call("list_ic_domain_accounts"), "HZ_IC_DOMAIN_ACCOUNT"),
               "an instant clone domain account")
    return Placement(
        vcenter_id=vc["id"], datacenter_id=dc["id"], host_or_cluster_id=hc["id"], resource_pool_id=rp["id"],
        vm_folder_id=folder["id"], datastore_id=ds["id"], parent_vm_id=vm["id"], base_snapshot_id=snap["id"],
        access_group_id=ag["id"], ic_domain_account_id=ic["id"],
        ad_container_rdn=os.environ.get("HZ_AD_CONTAINER") or None,
    )


def _provisioning(p: Placement) -> dict:
    return {
        "parent_vm_id": p.parent_vm_id,
        "base_snapshot_id": p.base_snapshot_id,
        "datacenter_id": p.datacenter_id,
        "vm_folder_id": p.vm_folder_id,
        "host_or_cluster_id": p.host_or_cluster_id,
        "resource_pool_id": p.resource_pool_id,
    }


def farm_spec(p: Placement, name: str, naming_pattern: str, description: str) -> dict:
    """AUTOMATED instant-clone farm with one RDS server (the API minimum)."""
    customization: dict = {"instant_clone_domain_account_id": p.ic_domain_account_id}
    if p.ad_container_rdn:
        customization["ad_container_rdn"] = p.ad_container_rdn
    return {
        "name": name,
        "display_name": name,
        "description": description,
        "type": "AUTOMATED",
        "access_group_id": p.access_group_id,
        "automated_farm_settings": {
            "vcenter_id": p.vcenter_id,
            "max_session_type": "UNLIMITED",
            "provisioning_settings": _provisioning(p),
            "storage_settings": {"datastores": [{"datastore_id": p.datastore_id}]},
            "customization_settings": customization,
            "pattern_naming_settings": {"naming_pattern": naming_pattern, "max_number_of_rds_servers": 1},
        },
    }


def desktop_pool_spec(p: Placement, name: str, naming_pattern: str, description: str) -> dict:
    """AUTOMATED instant-clone DEDICATED pool with exactly one machine, provisioned up front."""
    customization: dict = {"customization_type": "CLONE_PREP", "instant_clone_domain_account_id": p.ic_domain_account_id}
    if p.ad_container_rdn:
        customization["ad_container_rdn"] = p.ad_container_rdn
    return {
        "name": name,
        "display_name": name,
        "description": description,
        "type": "AUTOMATED",
        "source": "INSTANT_CLONE",
        "user_assignment": "DEDICATED",
        "automatic_user_assignment": True,
        "naming_method": "PATTERN",
        "access_group_id": p.access_group_id,
        "vcenter_id": p.vcenter_id,
        "provisioning_settings": _provisioning(p),
        "storage_settings": {"datastores": [{"datastore_id": p.datastore_id}]},
        "customization_settings": customization,
        "pattern_naming_settings": {
            "naming_pattern": naming_pattern,
            "max_number_of_machines": 1,
            "min_number_of_machines": 1,
            "number_of_spare_machines": 1,
            "provisioning_time": "UP_FRONT",
        },
    }
