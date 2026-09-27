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
    poll,
)
from .specs import farm_spec, resolve_placement

pytestmark = [
    pytest.mark.skipif(not (WRITES and DESTRUCTIVE),
                       reason="Destructive tests need HZ_LIVE_WRITES=1 and HZ_LIVE_DESTRUCTIVE=1 (lab only)"),
    pytest.mark.skipif(not (os.environ.get("HZ_BASE_VM") and os.environ.get("HZ_SNAPSHOT")),
                       reason="Set HZ_BASE_VM and HZ_SNAPSHOT (the post-agent-install snapshot)"),
]


async def _farm_spec(s: Session, name: str, tag: str) -> dict:
    p = await resolve_placement(s, base_vm_env="HZ_BASE_VM", snapshot_env="HZ_SNAPSHOT")
    # 12 chars: fits the 13-char limit for {n:fixed=2}. 1 server is the API minimum.
    return farm_spec(p, name, f"mcplv{tag}-{{n:fixed=2}}",
                     "Temporary farm created by the horizon-mcp live tests. Safe to delete.")


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
