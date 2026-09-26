"""Reversible write tests — opt-in with HZ_LIVE_WRITES=1. Use a lab, never production.

Each test creates and cleans up its own resources, or restores what it touched:
  - HZ_TEST_FARM: the one pre-existing farm these tests may modify (disabled then
    re-enabled, a no-op update), and the farm test application pools are published from.
  - HZ_TEST_GROUP: an AD group (name or SID) entitled to, then removed from, a test pool.
  - Global policies and general settings get a no-op round trip (identical object written back).
"""
import json
import os
import secrets
from contextlib import asynccontextmanager

import pytest

from horizon_mcp.tools.inventory import _FARM_UPDATE_FIELDS

from .harness import (
    NOOP_MARKER,
    WRITES,
    Approver,
    LiveToolError,
    Session,
    by_name,
    items,
    live_session,
    poll,
)
from .specs import APP_POOL_UPDATE_FIELDS

pytestmark = pytest.mark.skipif(not WRITES, reason="Write tests are opt-in: set HZ_LIVE_WRITES=1 (lab only)")
needs_farm = pytest.mark.skipif(not os.environ.get("HZ_TEST_FARM"),
                                reason="Set HZ_TEST_FARM to the name of a dedicated test RDS farm")
needs_group = pytest.mark.skipif(not os.environ.get("HZ_TEST_GROUP"),
                                 reason="Set HZ_TEST_GROUP to an AD group name or SID to entitle")

APP_EXECUTABLE = os.environ.get("HZ_TEST_APP_PATH", r"C:\Windows\System32\notepad.exe")


def unique_name() -> str:
    return f"mcp-live-{secrets.token_hex(4)}"


async def find_test_farm(s: Session) -> dict:
    name = os.environ["HZ_TEST_FARM"]
    farm = by_name(await s.list_all("list_rdsh_farms"), name)
    if not farm:
        pytest.fail(f"Test farm {name!r} not found — refusing to write to any other farm")
    return farm


# ── RDS farm: disable → enable, and a no-op update ───────────────────────────

@needs_farm
async def test_rdsh_farm_action_and_noop_update():
    approver = Approver()
    async with live_session("Farm writes", approver) as s:
        farm = await find_test_farm(s)
        fid = farm["id"]
        approver.allow(fid)
        before = await s.call("get_rdsh_farm", {"farm_id": fid}, label="get_rdsh_farm (before)")
        was_enabled = bool(before.get("enabled"))
        try:
            for action in ("disable", "enable") if was_enabled else ("enable", "disable"):
                res = await s.call("rdsh_farm_action", {"farm_ids": [fid], "action": action},
                                   label=f"rdsh_farm_action ({action})")
                assert res.get("succeeded") == 1 and not res.get("errors"), res
                now = await s.call("get_rdsh_farm", {"farm_id": fid}, label=f"get_rdsh_farm (after {action})")
                assert now.get("enabled") is (action == "enable")
            approver.assert_prompted(fid)  # disabling must have asked

            spec = {k: v for k, v in before.items() if k in _FARM_UPDATE_FIELDS}
            await s.call("update_rdsh_farm", {"farm_id": fid, "spec": spec}, label="update_rdsh_farm (no-op)")
            after = await s.call("get_rdsh_farm", {"farm_id": fid}, label="get_rdsh_farm (after update)")
            drift = sorted(k for k in _FARM_UPDATE_FIELDS if before.get(k) != after.get(k))
            assert not drift, f"Farm fields changed by a no-op update: {drift}"
        finally:
            ok, current, _ = await s.attempt("get_rdsh_farm", {"farm_id": fid}, label="get_rdsh_farm (final)")
            if ok and bool(current.get("enabled")) != was_enabled:
                await s.attempt("rdsh_farm_action", {"farm_ids": [fid], "action": "enable" if was_enabled else "disable"},
                                label="rdsh_farm_action (restore)")
    approver.assert_all_expected()


# ── Application pools on the test farm ───────────────────────────────────────

async def _find_app_pool(s: Session, name: str) -> dict | None:
    return by_name(await s.list_all("list_application_pools"), name)


async def _delete_app_pool(s: Session, pool: dict) -> None:
    await s.call("delete_application_pool", {"pool_id": pool["id"]})
    s.approver.assert_prompted(pool["id"])

    async def gone():
        return await _find_app_pool(s, pool["name"]) is None

    await poll(gone, timeout=120, interval=5, what=f"application pool {pool['name']} to disappear")


@asynccontextmanager
async def temp_app_pool(s: Session, farm_id: str):
    """Publish a uniquely named application pool on the farm; always delete it afterwards."""
    name = unique_name()
    ok, _, summary = await s.attempt("create_application_pool", {
        "name": name,
        "farm_id": farm_id,
        "executable_path": APP_EXECUTABLE,
        "display_name": name,
    })
    # The create response has no ID, so look the pool up by name — even when the tool
    # reported an error, in case Horizon created it anyway.
    try:
        pool = await poll(lambda: _find_app_pool(s, name), timeout=60 if ok else 10, interval=5,
                          what=f"application pool {name} to appear")
    except AssertionError:
        if not ok:
            raise LiveToolError(f"create_application_pool failed: {summary}") from None
        raise
    s.approver.allow(pool["id"])
    try:
        assert ok, f"create_application_pool reported an error but the pool was created: {summary}"
        yield pool
    finally:
        await _delete_app_pool(s, pool)


@needs_farm
async def test_application_pool_lifecycle():
    approver = Approver()
    async with live_session("Application pool lifecycle", approver) as s:
        farm = await find_test_farm(s)
        async with temp_app_pool(s, farm["id"]) as pool:
            pid = pool["id"]
            got = await s.call("get_application_pool", {"pool_id": pid})
            assert got.get("name") == pool["name"]
            assert got.get("farm_id") == farm["id"]
            assert str(got.get("executable_path", "")).lower() == APP_EXECUTABLE.lower()

            spec = {k: v for k, v in got.items() if k in APP_POOL_UPDATE_FIELDS}
            renamed = f"{pool['name']}-renamed"
            await s.call("update_application_pool", {"pool_id": pid, "spec": {**spec, "display_name": renamed}},
                         label="update_application_pool (rename)")
            changed = await s.call("get_application_pool", {"pool_id": pid}, label="get_application_pool (renamed)")
            assert changed.get("display_name") == renamed

            await s.call("update_application_pool", {"pool_id": pid, "spec": spec},
                         label="update_application_pool (restore)")
            restored = await s.call("get_application_pool", {"pool_id": pid}, label="get_application_pool (restored)")
            drift = sorted(k for k in APP_POOL_UPDATE_FIELDS if got.get(k) != restored.get(k))
            assert not drift, f"Fields differ after the round trip: {drift}"
    approver.assert_all_expected()


async def _resolve_group(s: Session) -> str:
    want = os.environ["HZ_TEST_GROUP"]
    if want.upper().startswith("S-1-"):
        await s.call("get_ad_user_or_group", {"ad_id": want})
        return want
    flt = json.dumps({"type": "Equals", "name": "name", "value": want})
    found = items(await s.call("search_ad_users_or_groups", {"filter": flt, "size": 50}))
    groups = [g for g in found if g.get("group") and want.lower() in
              (str(g.get("name", "")).lower(), str(g.get("login_name", "")).lower())]
    if len(groups) != 1:
        pytest.fail(f"HZ_TEST_GROUP {want!r} matched {len(groups)} AD groups — use the group's SID instead")
    return groups[0]["id"]


async def _entitled(s: Session, pool_id: str, label: str) -> set[str]:
    ok, data, summary = await s.attempt("get_pool_entitlement", {"pool_id": pool_id, "pool_type": "application"},
                                        label=f"get_pool_entitlement ({label})")
    if ok:
        return set((data or {}).get("ad_user_or_group_ids") or [])
    if "404" in summary:  # a pool with no entitlements may have no entitlement record
        return set()
    raise LiveToolError(f"get_pool_entitlement failed: {summary}")


def _assert_bulk_ok(result) -> None:
    for r in items(result) if isinstance(result, list) else [result]:
        assert not (r or {}).get("errors") and int((r or {}).get("status_code") or 200) < 400, result


@needs_farm
@needs_group
async def test_application_pool_entitlements_add_remove():
    approver = Approver()
    async with live_session("Application pool entitlements", approver) as s:
        farm = await find_test_farm(s)
        group_id = await _resolve_group(s)
        async with temp_app_pool(s, farm["id"]) as pool:
            pid = pool["id"]
            assert group_id not in await _entitled(s, pid, "before")
            args = {"pool_id": pid, "pool_type": "application", "ad_user_or_group_ids": [group_id]}
            added = False
            try:
                _assert_bulk_ok(await s.call("set_pool_entitlements", {**args, "action": "add"},
                                             label="set_pool_entitlements (add)"))
                added = True
                assert group_id in await _entitled(s, pid, "after add")

                _assert_bulk_ok(await s.call("set_pool_entitlements", {**args, "action": "remove"},
                                             label="set_pool_entitlements (remove)"))
                added = False
                approver.assert_prompted(pid)
                assert group_id not in await _entitled(s, pid, "after remove")
            finally:
                if added:
                    await s.attempt("set_pool_entitlements", {**args, "action": "remove"},
                                    label="set_pool_entitlements (cleanup)")
    approver.assert_all_expected()


# ── Global policies / settings: no-op round trips ────────────────────────────

async def _noop_round_trip(s: Session, approver: Approver, prefix: str, read, write) -> None:
    """Write back exactly what was read; assert the server reports and keeps no change."""
    approver.allow_noop(prefix)
    before = await read("before")
    try:
        await write(before, "no-op")
        approver.assert_prompted(NOOP_MARKER)
        after = await read("after")
        assert after == before, "Values changed after writing back an identical object"
    finally:
        current = await read("final")
        if current != before:  # put the original back — the only non-no-op write we allow
            approver.allow_restore(prefix)
            await write(before, "restore")


async def test_update_global_policies_noop():
    approver = Approver()
    async with live_session("Settings round trips", approver) as s:
        async def read(tag):
            return await s.call("get_global_policies", label=f"get_global_policies ({tag})")

        async def write(spec, tag):
            await s.call("update_global_policies", {"spec": spec}, label=f"update_global_policies ({tag})")

        await _noop_round_trip(s, approver, "Change Horizon global policies", read, write)
    approver.assert_all_expected()


async def test_update_settings_general_noop():
    approver = Approver()
    async with live_session("Settings round trips", approver) as s:
        async def read(tag):
            return await s.read_json_resource("horizon://config/settings/general")

        async def write(spec, tag):
            await s.call("update_settings", {"setting_type": "general", "spec": spec},
                         label=f"update_settings general ({tag})")

        await _noop_round_trip(s, approver, "Change Horizon general settings", read, write)
    approver.assert_all_expected()
