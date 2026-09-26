"""An offline fake Horizon REST API, for the lifecycle test's plan / dry run.

The real server runs in-process (fastmcp in-memory client, real elicitation) and every
httpx request it makes — login, API calls, logout — is answered by FakeHorizon through
httpx.MockTransport, so the real tool code, argument validation, confirmation prompts,
pagination and error formatting are all exercised. Nothing leaves the process.

The fake is deliberately strict where the real API is known to be (a farm can't be
deleted while it publishes apps; machine actions need an AVAILABLE machine; update
specs must not carry read-only fields; general settings reject their own GET output),
and answers the way this lab does where the lab has gaps (no event database, no image
streams). It seeds prefix-named leftovers and look-alike items that must survive cleanup.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest import mock

import httpx
from fastmcp import Client

from horizon_mcp import client as hz_client
from horizon_mcp.tools.inventory import _FARM_UPDATE_FIELDS

from .harness import Approver, Session
from .lifecycle import DEFAULT_PREFIX, Config, Result, run_e2e
from .specs import APP_POOL_UPDATE_FIELDS, POOL_READ_ONLY_FIELDS

FAKE_URL = "https://horizon.fake.invalid"
FAKE_TICKET = "FAKE-MSRA-TICKET-0123456789abcdef"
_ACCESS = "fake-access-token-0123456789"
_REFRESH = "fake-refresh-token-0123456789"


def _id(kind: str) -> str:
    return f"{kind}-{uuid.uuid4().hex[:12]}"


def _pub(obj: dict) -> dict:
    return {k: v for k, v in obj.items() if not k.startswith("_")}


class Reject(Exception):
    def __init__(self, status: int, message: str, key: str = "fake.rejected") -> None:
        super().__init__(message)
        self.status, self.message, self.key = status, message, key


def _bulk(ids, status: int = 200) -> list[dict]:
    return [{"id": i, "status_code": status} for i in ids]


class FakeHorizon:
    def __init__(self, *, prefix: str = DEFAULT_PREFIX, group: str = "e2e-group", user_login: str = "e2e-user",
                 users_connect: bool = True) -> None:
        self.prefix = prefix
        self.users_connect = users_connect
        self.requests: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.group = {"id": "S-1-5-21-0-0-0-1101", "name": group, "login_name": group, "group": True}
        self.user = {"id": "S-1-5-21-0-0-0-1102", "name": "E2E Test User", "login_name": user_login, "group": False}
        self.pools: dict[str, dict] = {}
        self.machines: dict[str, dict] = {}
        self.farms: dict[str, dict] = {}
        self.servers: dict[str, dict] = {}
        self.apps: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.ent: dict[tuple[str, str], set[str]] = {}
        self.policies = {"allow_multimedia_redirection": False, "allow_usb_access": True}
        self.general = {"client_idle_session_timeout_policy": "NEVER", "restricted_client_data": [{"type": "WINDOWS"}]}
        self.logged_in = False
        # Seeds: leftovers that cleanup must delete, and look-alikes it must leave alone.
        old_farm = self._add_farm(f"{prefix}farm-old1", ready=True)
        self._add_app(f"{prefix}app-old1", old_farm)
        self._add_pool(f"{prefix}vdi-old1", ready=True)
        prod_farm = self._add_farm("prod-farm", ready=True)
        self._add_app("prod-app", prod_farm)
        self._add_app(f"not-{prefix}app", prod_farm)
        prod_pool = self._add_pool("prod-vdi", ready=True)
        self.ent[("desktop", prod_pool)] = {"S-1-5-21-0-0-0-9999"}
        m = next(m for m in self.machines.values() if m["desktop_pool_id"] == prod_pool)
        sid = _id("session")
        self.sessions[sid] = {"id": sid, "user_id": "S-1-5-21-0-0-0-9999", "desktop_pool_id": prod_pool,
                              "machine_id": m["id"], "session_type": "DESKTOP", "session_state": "CONNECTED"}

    @property
    def protected_names(self) -> set[str]:
        return {"prod-farm", "prod-app", f"not-{self.prefix}app", "prod-vdi"}

    def names(self) -> set[str]:
        return {x["name"] for d in (self.pools, self.farms, self.apps) for x in d.values()}

    # ── object factories ──

    def _add_pool(self, name: str, *, ready: bool, spec: dict | None = None) -> str:
        pid = _id("pool")
        spec = spec or {}
        self.pools[pid] = {
            "id": pid, "name": name, "display_name": spec.get("display_name", name), "description": spec.get("description", ""),
            "type": spec.get("type", "AUTOMATED"), "source": spec.get("source", "INSTANT_CLONE"),
            "user_assignment": spec.get("user_assignment", "DEDICATED"), "naming_method": "PATTERN",
            "automatic_user_assignment": spec.get("automatic_user_assignment", True),
            "access_group_id": spec.get("access_group_id", "ag-root"), "vcenter_id": spec.get("vcenter_id", "vc-1"),
            "enabled": True, "enable_provisioning": True, "stop_provisioning_on_error": True,
            "delete_in_progress": False, "session_type": "DESKTOP",
            "provisioning_settings": spec.get("provisioning_settings", {}),
            "storage_settings": spec.get("storage_settings", {}),
            "customization_settings": spec.get("customization_settings", {}),
            "pattern_naming_settings": spec.get("pattern_naming_settings", {"max_number_of_machines": 1}),
            "provisioning_status_data": {"instant_clone_current_image_state": "READY"},
            "num_machines": 1, "num_sessions": 0, "created_at": 1,
        }
        mid = _id("machine")
        self.machines[mid] = {"id": mid, "name": f"{name[:10]}-01", "desktop_pool_id": pid, "user_ids": [],
                              "state": "AVAILABLE" if ready else "PROVISIONING",
                              "_next": [] if ready else ["CUSTOMIZING", "AVAILABLE"]}
        return pid

    def _add_farm(self, name: str, *, ready: bool, spec: dict | None = None) -> str:
        fid = _id("farm")
        afs = (spec or {}).get("automated_farm_settings") or {}
        self.farms[fid] = {
            "id": fid, "name": name, "display_name": (spec or {}).get("display_name", name),
            "description": (spec or {}).get("description", ""), "type": "AUTOMATED", "source": "INSTANT_CLONE",
            "access_group_id": (spec or {}).get("access_group_id", "ag-root"), "enabled": True,
            "delete_in_progress": False, "display_protocol_settings": {"default_display_protocol": "BLAST"},
            "load_balancer_settings": {}, "server_error_threshold": 0, "session_settings": {},
            "use_custom_script_for_load_balancing": False,
            "automated_farm_settings": {**afs, "enable_provisioning": True,
                                        "provisioning_status_data": {"instant_clone_current_image_state": "READY"}},
        }
        sid = _id("rds")
        self.servers[sid] = {"id": sid, "name": f"{name[:10]}-01", "farm_id": fid, "status": "OK",
                             "details_v3": {"state": "AVAILABLE" if ready else "PROVISIONING"},
                             "_next": [] if ready else ["CUSTOMIZING", "AVAILABLE"]}
        return fid

    def _add_app(self, name: str, farm_id: str, body: dict | None = None) -> str:
        aid = _id("app")
        body = body or {}
        self.apps[aid] = {"id": aid, "name": name, "display_name": body.get("display_name") or name, "farm_id": farm_id,
                          "executable_path": body.get("executable_path", r"C:\Windows\System32\notepad.exe"),
                          "enabled": True, "enable_pre_launch": False, "enable_client_restrictions": False,
                          "multi_session_mode": "DISABLED", "description": "", "publisher": "", "version": "",
                          "icon_ids": []}
        return aid

    # ── helpers ──

    @staticmethod
    def _advance(obj: dict, state_key: tuple[str, ...]) -> None:
        if obj.get("_next"):
            target = obj
            for k in state_key[:-1]:
                target = target[k]
            target[state_key[-1]] = obj["_next"].pop(0)

    @staticmethod
    def _filtered(rows: list[dict], params: dict) -> list[dict]:
        if params.get("filter"):
            f = json.loads(params["filter"])
            if f.get("type") == "Equals":
                rows = [r for r in rows if str(r.get(f["name"])) == str(f["value"])]
        return rows

    def _page(self, rows: list[dict], params: dict) -> list[dict]:
        rows = self._filtered(rows, params)
        page, size = int(params.get("page", 1)), int(params.get("size", 100))
        return [_pub(r) for r in rows[(page - 1) * size: page * size]]

    def _reap(self, store: dict[str, dict]) -> None:
        """Async deletes: an item marked delete_in_progress disappears after two more list calls."""
        for iid, item in list(store.items()):
            if item.get("delete_in_progress"):
                item["_ticks"] = item.get("_ticks", 2) - 1
                if item["_ticks"] < 0:
                    del store[iid]
                    self.deleted.append(item["name"])
                    for m in [m for m in self.machines.values() if m.get("desktop_pool_id") == iid]:
                        del self.machines[m["id"]]
                    for s in [s for s in self.servers.values() if s.get("farm_id") == iid]:
                        del self.servers[s["id"]]

    @staticmethod
    def _require(spec: dict, *paths: str) -> None:
        for p in paths:
            node: Any = spec
            for k in p.split("."):
                if not isinstance(node, dict) or k not in node:
                    raise Reject(400, f"{p} is required", "fake.required")
                node = node[k]

    @staticmethod
    def _only(spec: dict, allowed: set[str], what: str) -> None:
        extra = sorted(set(spec) - allowed)
        if extra:
            raise Reject(400, f"{what} does not accept: {', '.join(extra)}", "fake.unknown.field")

    def _machine_for(self, pool_id: str) -> dict | None:
        return next((m for m in self.machines.values() if m["desktop_pool_id"] == pool_id), None)

    def _spawn_sessions(self) -> None:
        """The simulated user connects to whatever the test user is entitled to."""
        if not self.users_connect:
            return
        uid = self.user["id"]
        for (ptype, pid), who in self.ent.items():
            if uid not in who or any(s.get("desktop_pool_id") == pid or s.get("_app_id") == pid
                                     for s in self.sessions.values()):
                continue
            sid = _id("session")
            if ptype == "desktop" and pid in self.pools:
                m = self._machine_for(pid)
                if not m or m["state"] != "AVAILABLE":
                    continue
                m["state"], m["user_ids"] = "CONNECTED", [uid]
                self.sessions[sid] = {"id": sid, "user_id": uid, "desktop_pool_id": pid, "machine_id": m["id"],
                                      "session_type": "DESKTOP", "session_state": "CONNECTED"}
            elif ptype == "application" and pid in self.apps:
                farm_id = self.apps[pid]["farm_id"]
                self.sessions[sid] = {"id": sid, "user_id": uid, "farm_id": farm_id, "session_type": "APPLICATION",
                                      "session_state": "CONNECTED", "_app_id": pid,
                                      "_apps": [{"remote_application_id": _id("ra"), "name": "notepad.exe",
                                                 "status": "RUNNING", "process_id": 4242}]}

    def _end_session(self, sid: str) -> None:
        ses = self.sessions.pop(sid, None)
        if ses and ses.get("machine_id") in self.machines:
            self.machines[ses["machine_id"]]["state"] = "AVAILABLE"

    # ── HTTP entry point ──

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        self.requests.append((method, path))
        params = dict(request.url.params)
        body = json.loads(request.content) if request.content else None
        try:
            if path in ("/rest/login", "/rest/refresh", "/rest/logout"):
                return self._auth(path, body)
            if request.headers.get("Authorization") != f"Bearer {_ACCESS}" or not self.logged_in:
                raise Reject(401, "Unauthorized", "fake.unauthorized")
            result = self._route(method, path.removeprefix("/rest"), params, body)
        except Reject as e:
            return httpx.Response(e.status, json={"errors": [{"error_key": e.key, "error_message": e.message}]})
        if result is None:
            return httpx.Response(204)
        return httpx.Response(200, json=result)

    def _auth(self, path: str, body: Any) -> httpx.Response:
        if path == "/rest/login":
            self.logged_in = True
            return httpx.Response(200, json={"access_token": _ACCESS, "refresh_token": _REFRESH})
        if (body or {}).get("refresh_token") != _REFRESH:
            return httpx.Response(400, json={"error_message": "invalid refresh token"})
        if path == "/rest/refresh":
            return httpx.Response(200, json={"access_token": _ACCESS})
        self.logged_in = False
        return httpx.Response(200)

    def _route(self, method: str, path: str, params: dict, body: Any) -> Any:
        for m, pattern, fn in self._routes():
            if m == method:
                hit = re.fullmatch(pattern, path)
                if hit:
                    return fn(params, body, *hit.groups())
        raise Reject(404, f"fake Horizon has no route for {method} {path}", "fake.no.route")

    def _routes(self):
        single = {"id": "cs-1"}
        return (
            # config
            ("GET", r"/config/v1/connection-servers", lambda p, b: [{"id": "cs-1", "name": "cs01"}]),
            ("GET", r"/config/v1/connection-servers/([^/]+)", lambda p, b, i: {"id": i, "name": "cs01"}),
            ("POST", r"/config/v1/connection-servers/action/backup", lambda p, b: _bulk(b or ["cs-1"])),
            ("GET", r"/config/v6/virtual-centers", lambda p, b: [{"id": "vc-1", "server_name": "vcenter"}]),
            ("GET", r"/config/v3/environment-properties", lambda p, b: {"local_connection_server_version": "fake"}),
            ("GET", r"/config/v9/settings", lambda p, b: {"general_settings": {}}),
            ("GET", r"/config/v1/global-policies", lambda p, b: dict(self.policies)),
            ("PUT", r"/config/v1/global-policies", self._put_policies),
            ("GET", r"/config/v1/settings/general", lambda p, b: json.loads(json.dumps(self.general))),
            ("PUT", r"/config/v1/settings/general", self._put_general),
            ("GET", r"/config/v1/licenses", lambda p, b: [{"license_mode": "SUBSCRIPTION"}]),
            ("GET", r"/config/v1/event-database", lambda p, b: {"event_database_configured": False}),
            ("GET", r"/config/v1/ic-domain-accounts", lambda p, b: [{"id": "ic-1", "username": "svc-ic"}]),
            ("GET", r"/config/v1/im-streams", lambda p, b: []),
            ("GET", r"/config/v1/gateways", lambda p, b: []),
            ("GET", r"/config/v1/local-access-groups", lambda p, b: [{"id": "ag-root", "name": "Root"}]),
            # monitor
            ("GET", r"/monitor/v1/health-metrics", lambda p, b: {"status": "OK"}),
            ("GET", r"/monitor/v4/connection-servers", lambda p, b: [{**single, "status": "OK"}]),
            ("GET", r"/monitor/v4/connection-servers/([^/]+)", lambda p, b, i: {"id": i, "status": "OK"}),
            ("GET", r"/monitor/v5/gateways", lambda p, b: []),
            ("GET", r"/monitor/v4/virtual-centers", lambda p, b: [{"id": "vc-1", "status": "OK"}]),
            ("GET", r"/monitor/v4/ad-domains", lambda p, b: [{"dns_name": "example.test"}]),
            ("GET", r"/monitor/v2/farms", lambda p, b: [{"id": f["id"], "name": f["name"], "status": "OK",
                                                         "rds_server_count": 1} for f in self.farms.values()]),
            ("GET", r"/monitor/v4/rds-servers", self._rds_servers),
            ("GET", r"/monitor/v3/desktop-pools/metrics", lambda p, b: {}),
            ("GET", r"/monitor/v1/sessions/metrics", lambda p, b: {}),
            ("GET", r"/monitor/v2/machines/count-metrics", lambda p, b: {}),
            ("GET", r"/monitor/v2/system-metrics", lambda p, b: {}),
            ("GET", r"/monitor/v1/rds-servers/count-metrics", lambda p, b: {}),
            ("GET", r"/monitor/v1/licenses/usage-metrics", lambda p, b: {}),
            # external
            ("GET", r"/external/v4/ad-users-or-groups", lambda p, b: self._page([self.group, self.user], p)),
            ("GET", r"/external/v4/ad-users-or-groups/([^/]+)", self._get_principal),
            ("GET", r"/external/v3/ad-domains", lambda p, b: [{"id": "dom-1", "dns_name": "example.test"}]),
            ("GET", r"/external/v1/ad-domains/([^/]+)/ad-containers", lambda p, b, i: [{"rdn": "OU=VDI"}]),
            ("GET", r"/external/v1/domains", lambda p, b: {"EXAMPLE": "example.test"}),
            ("GET", r"/external/v2/audit-events", self._no_event_db),
            ("GET", r"/external/v2/base-vms", lambda p, b: [{"id": "vm-1", "name": "base-image"}]),
            ("GET", r"/external/v2/base-snapshots", lambda p, b: [{"id": "snap-1", "name": "agent-installed"}]),
            ("GET", r"/external/v1/datacenters", lambda p, b: [{"id": "dc-1", "name": "dc"}]),
            ("GET", r"/external/v1/vm-folders", lambda p, b: [{"id": "folder-1", "name": "vdi"}]),
            ("GET", r"/external/v1/hosts-or-clusters",
             lambda p, b: [{"id": "hc-1", "details": {"name": "cluster", "cluster": True}}]),
            ("GET", r"/external/v1/datastores", lambda p, b: [{"id": "ds-1", "name": "datastore"}]),
            ("GET", r"/external/v1/resource-pools", lambda p, b: [{"id": "rp-1", "name": "Resources"}]),
            ("GET", r"/external/v1/network-labels", lambda p, b: [{"id": "net-1"}]),
            ("GET", r"/external/v1/network-interface-cards", lambda p, b: [{"id": "nic-1"}]),
            ("GET", r"/external/v1/datastore-clusters", lambda p, b: []),
            ("GET", r"/external/v1/vm-templates", lambda p, b: []),
            ("GET", r"/external/v1/customization-specifications", lambda p, b: []),
            # desktop pools & machines
            ("GET", r"/inventory/v13/desktop-pools", self._list_pools),
            ("GET", r"/inventory/v13/desktop-pools/([^/]+)", lambda p, b, i: _pub(self._get(self.pools, i))),
            ("POST", r"/inventory/v1/desktop-pools", self._create_pool),
            ("PUT", r"/inventory/v1/desktop-pools/([^/]+)", self._update_pool),
            ("DELETE", r"/inventory/v1/desktop-pools/([^/]+)", lambda p, b, i: self._mark_deleted(self.pools, i)),
            ("POST", r"/inventory/v1/desktop-pools/action/([a-z-]+)", self._pool_action),
            ("GET", r"/inventory/v1/machines", self._list_machines),
            ("GET", r"/inventory/v1/machines/([^/]+)", self._get_machine),
            ("POST", r"/inventory/v1/machines/action/([a-z-]+)", self._machine_action),
            ("POST", r"/inventory/v1/machines/([^/]+)/action/(assign-users|unassign-users)", self._assign),
            # farms & application pools
            ("GET", r"/inventory/v10/farms", self._list_farms),
            ("GET", r"/inventory/v10/farms/([^/]+)", lambda p, b, i: _pub(self._get(self.farms, i))),
            ("POST", r"/inventory/v1/farms", self._create_farm),
            ("PUT", r"/inventory/v1/farms/([^/]+)", self._update_farm),
            ("DELETE", r"/inventory/v1/farms/([^/]+)", self._delete_farm),
            ("GET", r"/inventory/v1/application-pools", lambda p, b: self._page(list(self.apps.values()), p)),
            ("GET", r"/inventory/v1/application-pools/([^/]+)", lambda p, b, i: _pub(self._get(self.apps, i))),
            ("POST", r"/inventory/v1/application-pools", self._create_app),
            ("PUT", r"/inventory/v1/application-pools/([^/]+)", self._update_app),
            ("DELETE", r"/inventory/v1/application-pools/([^/]+)", self._delete_app),
            # sessions
            ("GET", r"/inventory/v1/sessions", self._list_sessions),
            ("GET", r"/inventory/v1/sessions/([^/]+)", lambda p, b, i: _pub(self._get(self.sessions, i))),
            ("POST", r"/inventory/v1/sessions/action/([a-z-]+)", self._session_action),
            # entitlements
            ("GET", r"/entitlements/v1/(desktop|application)-pools", self._list_ent),
            ("GET", r"/entitlements/v1/(desktop|application)-pools/([^/]+)", self._get_ent),
            ("POST", r"/entitlements/v1/(desktop|application)-pools", lambda p, b, t: self._set_ent(t, b, "add")),
            ("PUT", r"/entitlements/v1/(desktop)-pools", lambda p, b, t: self._set_ent(t, b, "replace")),
            ("DELETE", r"/entitlements/v1/(desktop|application)-pools", lambda p, b, t: self._set_ent(t, b, "remove")),
            # help desk
            ("GET", r"/helpdesk/v3/logon-timing/logon-segment", lambda p, b: self._diag(p, {"logon_time_ms": 1234})),
            ("GET", r"/helpdesk/v3/performance/display-protocol", lambda p, b: self._diag(p, {"frame_rate": 30})),
            ("GET", r"/helpdesk/v2/performance/historical-data", lambda p, b: self._diag(p, {"samples": []})),
            ("GET", r"/helpdesk/v2/performance/process", lambda p, b: self._diag(p, [])),
            ("GET", r"/helpdesk/v2/performance/remote-application",
             lambda p, b: self._diag(p, self.sessions.get(p.get("internal_session_id"), {}).get("_apps", []))),
            ("GET", r"/helpdesk/v2/remote-assistant-ticket", lambda p, b: self._diag(p, {"ticket": FAKE_TICKET})),
            ("POST", r"/helpdesk/v1/performance/remote-application/action/end-remote-application", self._end_app),
        )

    # ── handlers ──

    @staticmethod
    def _get(store: dict, iid: str) -> dict:
        if iid not in store:
            raise Reject(404, f"{iid} not found", "fake.not.found")
        return store[iid]

    def _get_principal(self, p, b, i):
        hit = next((x for x in (self.group, self.user) if x["id"] == i), None)
        if not hit:
            raise Reject(404, "not found")
        return hit

    def _no_event_db(self, p, b):
        raise Reject(409, "Event database is not configured", "event.database.not.configured")

    def _put_policies(self, p, b):
        self.policies = dict(b)

    def _put_general(self, p, b):
        for entry in b.get("restricted_client_data") or []:
            if "version" not in entry:
                raise Reject(400, f"Restricted client version must be set for client type {entry.get('type')}",
                             "restricted_client_data.version.unset")
        self.general = b

    def _rds_servers(self, p, b):
        out = [json.loads(json.dumps(_pub(s))) for s in self.servers.values()]
        for s in self.servers.values():
            self._advance(s, ("details_v3", "state"))
        return out

    def _list_pools(self, p, b):
        self._reap(self.pools)
        return self._page(list(self.pools.values()), p)

    def _create_pool(self, p, spec):
        self._require(spec, "name", "type", "source", "user_assignment", "naming_method", "access_group_id",
                      "vcenter_id", "provisioning_settings.parent_vm_id", "provisioning_settings.base_snapshot_id",
                      "provisioning_settings.datacenter_id", "provisioning_settings.vm_folder_id",
                      "provisioning_settings.host_or_cluster_id", "provisioning_settings.resource_pool_id",
                      "storage_settings.datastores", "customization_settings.customization_type",
                      "customization_settings.instant_clone_domain_account_id",
                      "pattern_naming_settings.naming_pattern", "pattern_naming_settings.max_number_of_machines")
        if any(x["name"] == spec["name"] for x in self.pools.values()):
            raise Reject(409, "a pool with that name exists", "fake.duplicate")
        self._add_pool(spec["name"], ready=False, spec=spec)  # 201, no body

    def _update_pool(self, p, spec, i):
        pool = self._get(self.pools, i)
        bad = sorted(set(spec) & POOL_READ_ONLY_FIELDS)
        if bad:
            raise Reject(400, f"read-only fields in the update spec: {', '.join(bad)}", "fake.read.only")
        pool.update(spec)

    def _mark_deleted(self, store: dict, i: str):
        item = self._get(store, i)
        if item.get("delete_in_progress"):
            raise Reject(400, "delete already in progress", "fake.delete.in.progress")
        item["delete_in_progress"] = True

    def _pool_action(self, p, ids, action):
        key, value = {"enable": ("enabled", True), "disable": ("enabled", False),
                      "enable-provisioning": ("enable_provisioning", True),
                      "disable-provisioning": ("enable_provisioning", False)}[action]
        for i in ids:
            self._get(self.pools, i)[key] = value
        return _bulk(ids, 204)

    def _list_machines(self, p, b):
        page = self._page(list(self.machines.values()), p)  # show the current state, then move on
        for m in self.machines.values():
            self._advance(m, ("state",))
        return page

    def _get_machine(self, p, b, i):
        return _pub(self._get(self.machines, i))

    _NEEDS = {"enter-maintenance": "AVAILABLE", "exit-maintenance": "MAINTENANCE", "restart": "AVAILABLE",
              "reset": "AVAILABLE", "shutdown": "AVAILABLE", "rebuild": "AVAILABLE", "archive": "AVAILABLE"}

    def _machine_action(self, p, body, action):
        ids = body["machineIds"] if isinstance(body, dict) else body
        if action in ("shutdown", "restart") and not (isinstance(body, dict) and "forceOperation" in body):
            raise Reject(400, "expected {machineIds, forceOperation}")
        out = []
        for i in ids:
            m = self._get(self.machines, i)
            need = self._NEEDS.get(action)
            if need and m["state"] != need:  # the real API's misleading 400
                raise Reject(400, f"machine {m['name']} is {m['state']}, not {need}", "fake.machine.state")
            if action in ("recover", "rebuild", "archive"):
                out.append({"id": i, "status_code": 400,
                            "errors": [{"error_key": f"fake.{action}.not.applicable",
                                        "error_message": f"{action} does not apply to this instant clone"}]})
                continue
            m["state"], m["_next"] = {
                "enter-maintenance": ("MAINTENANCE", []), "exit-maintenance": ("AVAILABLE", []),
                "restart": ("IN_PROGRESS", ["AVAILABLE"]), "reset": ("IN_PROGRESS", ["AVAILABLE"]),
                "shutdown": ("AGENT_UNREACHABLE", []),
            }[action]
            out.append({"id": i, "status_code": 200})
        return out

    def _assign(self, p, body, i, action):
        m = self._get(self.machines, i)
        if self.pools[m["desktop_pool_id"]]["user_assignment"] != "DEDICATED":
            raise Reject(400, "not a dedicated pool")
        users = set(body["user_ids"])
        m["user_ids"] = sorted(set(m["user_ids"]) | users) if action == "assign-users" else \
            [u for u in m["user_ids"] if u not in users]

    def _list_farms(self, p, b):
        self._reap(self.farms)
        return self._page(list(self.farms.values()), p)

    def _create_farm(self, p, spec):
        self._require(spec, "name", "type", "access_group_id", "automated_farm_settings.vcenter_id",
                      "automated_farm_settings.max_session_type",
                      "automated_farm_settings.provisioning_settings.parent_vm_id",
                      "automated_farm_settings.provisioning_settings.base_snapshot_id",
                      "automated_farm_settings.storage_settings.datastores",
                      "automated_farm_settings.customization_settings.instant_clone_domain_account_id",
                      "automated_farm_settings.pattern_naming_settings.max_number_of_rds_servers")
        self._add_farm(spec["name"], ready=False, spec=spec)

    def _update_farm(self, p, spec, i):
        self._only(spec, _FARM_UPDATE_FIELDS, "FarmUpdateSpec")
        self._get(self.farms, i).update(spec)

    def _delete_farm(self, p, b, i):
        if any(a["farm_id"] == i for a in self.apps.values()):
            raise Reject(400, "the farm still publishes application pools", "fake.farm.in.use")
        self._mark_deleted(self.farms, i)

    def _create_app(self, p, body):
        self._require(body, "name", "farm_id", "executable_path")
        self._get(self.farms, body["farm_id"])
        self._add_app(body["name"], body["farm_id"], body)

    def _update_app(self, p, spec, i):
        self._only(spec, APP_POOL_UPDATE_FIELDS, "ApplicationPoolUpdateSpec")
        self._get(self.apps, i).update(spec)

    def _delete_app(self, p, b, i):
        app = self._get(self.apps, i)
        del self.apps[i]
        self.deleted.append(app["name"])

    def _list_sessions(self, p, b):
        self._spawn_sessions()
        return self._page(list(self.sessions.values()), p)

    def _session_action(self, p, body, action):
        ids = (body.get("session_ids") if isinstance(body, dict) else body) or []
        for i in ids:
            self._get(self.sessions, i)
        for i in ids:
            if action == "disconnect":
                self.sessions[i]["session_state"] = "DISCONNECTED"
            elif action == "logoff":
                if p.get("forced") not in ("true", "false"):
                    raise Reject(400, "forced must be a query parameter")
                self._end_session(i)
            elif action in ("reset", "restart"):
                mid = self.sessions[i].get("machine_id")
                self._end_session(i)
                if mid in self.machines:
                    self.machines[mid]["state"], self.machines[mid]["_next"] = "IN_PROGRESS", ["AVAILABLE"]
        return _bulk(ids)

    def _diag(self, p, value):
        if p.get("internal_session_id") not in self.sessions:
            raise Reject(404, "session not found")
        return value

    def _end_app(self, p, b):
        ses = self._get(self.sessions, p.get("session_id", ""))
        before = len(ses.get("_apps", []))
        ses["_apps"] = [a for a in ses.get("_apps", []) if a["remote_application_id"] != p.get("remote_application_id")]
        if len(ses["_apps"]) == before:
            raise Reject(404, "remote application not found")

    def _list_ent(self, p, b, t):
        return [{"id": pid, "ad_user_or_group_ids": sorted(who)} for (pt, pid), who in self.ent.items() if pt == t and who]

    def _get_ent(self, p, b, t, i):
        who = self.ent.get((t, i))
        if not who:  # what the lab does for a pool with no entitlements
            raise Reject(404, "no entitlements", "fake.not.found")
        return {"id": i, "ad_user_or_group_ids": sorted(who)}

    def _set_ent(self, t, spec, action):
        for entry in spec:
            store = self.pools if t == "desktop" else self.apps
            self._get(store, entry["id"])
            key, ids = (t, entry["id"]), set(entry["ad_user_or_group_ids"])
            cur = self.ent.setdefault(key, set())
            self.ent[key] = cur | ids if action == "add" else ids if action == "replace" else cur - ids
        return [{"id": e["id"]} for e in spec]

    # ── installing it ──

    @contextlib.contextmanager
    def installed(self):
        """Route every httpx.AsyncClient in this process to the fake, with a clean server state."""
        fake = self
        orig_init = httpx.AsyncClient.__init__

        def init(client_self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(fake.handle)
            orig_init(client_self, *args, **kwargs)

        keys = ("HORIZON_BASE_URL", "HORIZON_ACCESS_TOKEN", "HORIZON_REFRESH_TOKEN", "HORIZON_CONFIRMATION",
                "HORIZON_AUDIT_LOG", "HORIZON_EXPOSE_TOKENS")
        saved_env = {k: os.environ.get(k) for k in keys}
        saved_state = (hz_client._client, hz_client._refresh_token)
        for k in keys:
            os.environ.pop(k, None)
        os.environ.update(HORIZON_BASE_URL=FAKE_URL, HORIZON_CONFIRMATION="elicit", HORIZON_AUDIT_LOG=os.devnull)
        hz_client._client, hz_client._refresh_token = None, None
        server_log = logging.getLogger("fastmcp")  # it logs a traceback for every tool error
        saved_level = server_log.level
        server_log.setLevel(logging.CRITICAL)
        try:
            with mock.patch.object(httpx.AsyncClient, "__init__", init):
                yield self
        finally:
            server_log.setLevel(saved_level)
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            hz_client._client, hz_client._refresh_token = saved_state


def offline_config(*, wait_for_session: bool = True, prefix: str = DEFAULT_PREFIX) -> Config:
    return Config(prefix=prefix, group="e2e-group", user="EXAMPLE\\e2e-user", wait_for_session=wait_for_session,
                  provision_timeout=10, session_timeout=10, session_grace=0, poll_interval=0, base_url=FAKE_URL,
                  tag="f00d")


def run_offline(*, wait_for_session: bool = True, prefix: str = DEFAULT_PREFIX) -> tuple[Result, FakeHorizon]:
    """Run the whole lifecycle flow against the fake. Returns the result and the fake's final state."""
    from horizon_mcp.server import mcp

    cfg = offline_config(wait_for_session=wait_for_session, prefix=prefix)
    fake = FakeHorizon(prefix=prefix, group=cfg.group, user_login="e2e-user", users_connect=wait_for_session)
    rows: list[dict] = []
    prompts: list[dict] = []

    @asynccontextmanager
    async def opener(group: str, approver: Approver):
        async with Client(mcp, elicitation_handler=approver) as c:
            yield Session(c, group, approver, rows=rows)

    with fake.installed():
        result = asyncio.run(run_e2e(opener, cfg, rows=rows, prompts=prompts))
    return result, fake
