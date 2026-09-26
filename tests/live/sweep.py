"""Read-only tool sweep: every read-only tool, chaining IDs from list results into gets.

`run_sweep` is written against a tiny runner interface (`call` / `skip`) so the same code
can be dry-run offline to enumerate check labels for pytest parametrization — every
branch records exactly one row per label, whether the call runs or is skipped.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Protocol

from .harness import credentials, first, items, pick, walk


class Runner(Protocol):
    async def call(self, tool: str, args: dict | None = None, label: str | None = None) -> Any: ...
    def skip(self, label: str, reason: str) -> None: ...
    def section(self, name: str) -> None: ...


def find_host_or_cluster(nodes: Any, want: str | None = None) -> dict | None:
    """DFS the hosts-or-clusters tree for the node named/with the id `want`, else prefer a
    cluster, else any host."""
    found = [n for n in walk(items(nodes) or nodes) if n.get("id") and isinstance(n.get("details"), dict)]
    if want:
        return next((n for n in found if want in (n["id"], n["details"].get("name"), n["details"].get("path"))), None)
    clusters = [n for n in found if n["details"].get("cluster")]
    return (clusters or found or [None])[0]


async def run_sweep(r: Runner) -> None:
    r.section("Auth")
    login = await r.call("horizon_login", credentials())
    if login is None:
        raise RuntimeError("horizon_login failed, so the sweep stopped — see the horizon_login check")
    refresh = (login or {}).get("refresh_token", "") if isinstance(login, dict) else ""
    if refresh:
        refreshed = await r.call("horizon_refresh_token", {"refresh_token": refresh})
        if isinstance(refreshed, dict) and refreshed.get("refresh_token"):
            refresh = refreshed["refresh_token"]
    else:
        r.skip("horizon_refresh_token", "Login returned no refresh token")

    r.section("Settings & infrastructure")
    cs = first(await r.call("list_connection_servers"))
    if cs:
        await r.call("get_connection_server", {"server_id": cs["id"]})
    else:
        r.skip("get_connection_server", "No connection server returned")
    for t in ("list_virtual_centers", "get_environment_properties", "get_settings", "get_global_policies",
              "list_licenses", "get_event_database", "list_ic_domain_accounts", "list_gateways", "get_api_coverage"):
        await r.call(t)
    stream = first(await r.call("list_image_management", {"resource": "streams"},
                                label="list_image_management (streams)"))
    for res in ("versions", "tags"):
        label = f"list_image_management ({res})"
        if stream:
            await r.call("list_image_management", {"resource": res, "stream_id": stream["id"]}, label=label)
        else:
            r.skip(label, "No image streams exist")

    r.section("Monitoring")
    await r.call("get_infrastructure_health")
    if cs:
        await r.call("get_connection_server_health", {"server_id": cs["id"]})
    else:
        r.skip("get_connection_server_health", "No connection server returned")
    await r.call("get_metrics")
    await r.call("list_audit_events", {"size": 25})

    r.section("vCenter discovery")
    vc = pick(await r.call("list_virtual_centers", label="list_virtual_centers (for chaining)"), "HZ_VCENTER")
    chain = ("list_datacenters", "list_vm_folders", "list_hosts_or_clusters", "list_datastores",
             "list_resource_pools", "list_network_labels", "list_datastore_clusters", "list_base_vms",
             "list_base_vm_snapshots", "list_network_interface_cards", "list_vm_templates",
             "list_customization_specifications")
    if not vc:
        for t in chain:
            r.skip(t, "No vCenter returned")
    else:
        v = {"vcenter_id": vc["id"]}
        dc = pick(await r.call("list_datacenters", v), "HZ_DATACENTER")
        hc = None
        if dc:
            await r.call("list_vm_folders", {**v, "datacenter_id": dc["id"]})
            hc = find_host_or_cluster(await r.call("list_hosts_or_clusters", {**v, "datacenter_id": dc["id"]}),
                                      os.environ.get("HZ_CLUSTER"))
        else:
            for t in ("list_vm_folders", "list_hosts_or_clusters"):
                r.skip(t, "No datacenter returned")
        for t in ("list_datastores", "list_resource_pools", "list_network_labels", "list_datastore_clusters"):
            if hc:
                await r.call(t, {**v, "host_or_cluster_id": hc["id"]})
            else:
                r.skip(t, "No host or cluster found")
        vm = pick(await r.call("list_base_vms", v), "HZ_BASE_VM")
        for t in ("list_base_vm_snapshots", "list_network_interface_cards"):
            if vm:
                await r.call(t, {**v, "base_vm_id": vm["id"]})
            else:
                r.skip(t, "No base VM returned")
        for t in ("list_vm_templates", "list_customization_specifications"):
            await r.call(t, v)

    r.section("AD & entitlements")
    dom = first(await r.call("list_ad_domains"))
    if dom:
        await r.call("list_ad_containers", {"domain_id": dom["id"]})
    else:
        r.skip("list_ad_containers", "No AD domain returned")
    await r.call("get_domain_netbios_map")
    u = first(await r.call("search_ad_users_or_groups", {"size": 10}))
    if u:
        await r.call("get_ad_user_or_group", {"ad_id": u["id"]})
    else:
        r.skip("get_ad_user_or_group", "No AD users/groups returned")
    for pt in ("desktop", "application"):
        await r.call("list_pool_entitlements", {"pool_type": pt}, label=f"list_pool_entitlements ({pt})")

    r.section("Inventory")
    pool = first(await r.call("list_desktop_pools"))
    if pool:
        await r.call("get_desktop_pool", {"pool_id": pool["id"]})
        await r.call("get_pool_entitlement", {"pool_id": pool["id"], "pool_type": "desktop"},
                     label="get_pool_entitlement (desktop)")
    else:
        r.skip("get_desktop_pool", "No desktop pools exist")
        r.skip("get_pool_entitlement (desktop)", "No desktop pools exist")
    m = first(await r.call("list_machines"))
    if m:
        await r.call("get_machine", {"machine_id": m["id"]})
    else:
        r.skip("get_machine", "No machines exist")
    farms = await r.call("list_rdsh_farms")
    test_farm = os.environ.get("HZ_TEST_FARM")
    farm = first(farms, lambda x: x.get("name") == test_farm) or first(farms)
    if farm:
        await r.call("get_rdsh_farm", {"farm_id": farm["id"]})
    else:
        r.skip("get_rdsh_farm", "No RDS farms exist")
    app = first(await r.call("list_application_pools"))
    if app:
        await r.call("get_application_pool", {"pool_id": app["id"]})
        await r.call("get_pool_entitlement", {"pool_id": app["id"], "pool_type": "application"},
                     label="get_pool_entitlement (application)")
    else:
        r.skip("get_application_pool", "No application pools exist")
        r.skip("get_pool_entitlement (application)", "No application pools exist")

    r.section("Sessions")
    s = first(await r.call("list_sessions"))
    if s:
        await r.call("get_session", {"session_id": s["id"]})
        await r.call("diagnose_session", {"session_id": s["id"]})
    else:
        for t in ("get_session", "diagnose_session"):
            r.skip(t, "No active user sessions")

    r.section("Auth")
    if refresh:
        await r.call("horizon_logout", {"refresh_token": refresh})
    else:
        r.skip("horizon_logout", "No refresh token to log out with")


class _DryRunner:
    """Records labels without calling anything; every call 'succeeds' with no data."""

    def __init__(self) -> None:
        self.labels: list[str] = []

    async def call(self, tool, args=None, label=None):
        self.labels.append(label or tool)
        return {}

    def skip(self, label, reason):
        self.labels.append(label)

    def section(self, name):
        pass


def planned_checks() -> list[str]:
    """Every check label the sweep can produce (collected offline)."""
    dry = _DryRunner()
    asyncio.run(run_sweep(dry))
    return list(dict.fromkeys(dry.labels))
