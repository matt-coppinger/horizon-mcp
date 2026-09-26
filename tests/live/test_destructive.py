"""Destructive test: create a throwaway RDS farm, then delete it with delete_rdsh_farm.

Opt-in with BOTH HZ_LIVE_WRITES=1 and HZ_LIVE_DESTRUCTIVE=1. Use a lab, never production.
Creating an AUTOMATED farm provisions a real instant-clone RDS host in vCenter, so this
can take many minutes (HZ_LIVE_PROVISION_TIMEOUT, default 1800s, bounds each wait).

Required: HZ_BASE_VM and HZ_SNAPSHOT (name or ID). Pick the snapshot taken AFTER the
Horizon Agent was installed — the wrong one breaks agent customization.
Optional overrides (name or ID; default: the first one listed): HZ_VCENTER,
HZ_DATACENTER, HZ_CLUSTER, HZ_RESOURCE_POOL, HZ_VM_FOLDER, HZ_DATASTORE,
HZ_ACCESS_GROUP, HZ_IC_DOMAIN_ACCOUNT; HZ_AD_CONTAINER (an RDN) is passed as-is.
"""
import os
import secrets

import pytest

from .harness import (
    DESTRUCTIVE,
    PROVISION_TIMEOUT,
    WRITES,
    Approver,
    LiveToolError,
    Session,
    by_name,
    live_session,
    pick,
    poll,
)
from .sweep import find_host_or_cluster

pytestmark = [
    pytest.mark.skipif(not (WRITES and DESTRUCTIVE),
                       reason="Destructive tests need HZ_LIVE_WRITES=1 and HZ_LIVE_DESTRUCTIVE=1 (lab only)"),
    pytest.mark.skipif(not (os.environ.get("HZ_BASE_VM") and os.environ.get("HZ_SNAPSHOT")),
                       reason="Set HZ_BASE_VM and HZ_SNAPSHOT (the post-agent-install snapshot)"),
]


def _need(value, what: str):
    if not value:
        pytest.fail(f"Could not resolve {what} for the test farm — set the matching HZ_* override")
    return value


async def _farm_spec(s: Session, name: str, tag: str) -> dict:
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
    vm = _need(pick(await s.call("list_base_vms", v), "HZ_BASE_VM"), "HZ_BASE_VM")
    snap = _need(pick(await s.call("list_base_vm_snapshots", {**v, "base_vm_id": vm["id"]}), "HZ_SNAPSHOT"),
                 "HZ_SNAPSHOT on that base VM")
    ag = _need(pick(await s.read_json_resource("horizon://config/local-access-groups"), "HZ_ACCESS_GROUP"),
               "an access group")
    ic = _need(pick(await s.call("list_ic_domain_accounts"), "HZ_IC_DOMAIN_ACCOUNT"),
               "an instant clone domain account")

    customization = {"instant_clone_domain_account_id": ic["id"]}
    if os.environ.get("HZ_AD_CONTAINER"):
        customization["ad_container_rdn"] = os.environ["HZ_AD_CONTAINER"]
    return {
        "name": name,
        "display_name": name,
        "description": "Temporary farm created by the horizon-mcp live tests. Safe to delete.",
        "type": "AUTOMATED",
        "access_group_id": ag["id"],
        "automated_farm_settings": {
            "vcenter_id": vc["id"],
            "max_session_type": "UNLIMITED",
            "provisioning_settings": {
                "parent_vm_id": vm["id"],
                "base_snapshot_id": snap["id"],
                "datacenter_id": dc["id"],
                "vm_folder_id": folder["id"],
                "host_or_cluster_id": hc["id"],
                "resource_pool_id": rp["id"],
            },
            "storage_settings": {"datastores": [{"datastore_id": ds["id"]}]},
            "customization_settings": customization,
            # 12 chars: fits the 13-char limit for {n:fixed=2}. 1 server is the API minimum.
            "pattern_naming_settings": {"naming_pattern": f"mcplv{tag}-{{n:fixed=2}}", "max_number_of_rds_servers": 1},
        },
    }


async def _find_farm(s: Session, name: str) -> dict | None:
    return by_name(await s.list_all("list_rdsh_farms"), name)


async def _delete_farm(s: Session, farm: dict) -> None:
    """Delete, retrying while Horizon refuses (e.g. provisioning still running), then wait until gone."""
    async def delete():
        ok, _, summary = await s.attempt("delete_rdsh_farm", {"farm_id": farm["id"]})
        if not ok and "Cancelled by the user" in summary:
            raise LiveToolError(f"delete_rdsh_farm confirmation was cancelled: {summary}")
        return ok

    try:
        await poll(delete, timeout=PROVISION_TIMEOUT, interval=30, what=f"delete_rdsh_farm({farm['name']}) to succeed")
        s.approver.assert_prompted(farm["id"])

        async def gone():
            return await _find_farm(s, farm["name"]) is None

        await poll(gone, timeout=PROVISION_TIMEOUT, interval=15, what=f"farm {farm['name']} to disappear")
    except BaseException:
        print(f"\n  !! MANUAL CLEANUP MAY BE NEEDED: RDS farm {farm['name']} ({farm['id']})")
        raise


async def test_create_and_delete_rdsh_farm():
    approver = Approver()
    tag = secrets.token_hex(2)
    name = f"mcp-live-{tag}{secrets.token_hex(2)}"
    async with live_session("RDS farm create/delete", approver) as s:
        spec = await _farm_spec(s, name, tag)
        ok, _, summary = await s.attempt("create_rdsh_farm", {"spec": spec}, timeout=300)
        # Look the farm up by name even if the tool reported an error, so a farm Horizon
        # created anyway is still cleaned up.
        try:
            farm = await poll(lambda: _find_farm(s, name), timeout=300 if ok else 30, interval=10,
                              what=f"farm {name} to appear")
        except AssertionError:
            if not ok:
                raise LiveToolError(f"create_rdsh_farm failed: {summary}") from None
            raise
        approver.allow(farm["id"])
        try:
            assert ok, f"create_rdsh_farm reported an error but the farm was created: {summary}"
            got = await s.call("get_rdsh_farm", {"farm_id": farm["id"]})
            assert got.get("name") == name
        finally:
            await _delete_farm(s, farm)  # the delete under test, and the cleanup
    approver.assert_all_expected()
