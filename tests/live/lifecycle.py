"""End-to-end lifecycle: every tool the server exposes, against resources the run creates itself.

The flow is written against a Session (harness.py), so the same code runs live over MCP
stdio (test_lifecycle.py) or offline against an in-process fake Horizon (fake_horizon.py)
for the plan / dry run:

    uv run python -m tests.live.lifecycle --plan

Everything it creates is named with a fixed prefix (HZ_E2E_PREFIX, default "mcp-e2e-"),
and the only things it ever deletes, disables or restarts are items whose name starts
with that prefix — leftovers from earlier runs, or what this run created.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from horizon_mcp.tools.inventory import _FARM_UPDATE_FIELDS

from .harness import (
    CALL_TIMEOUT,
    NOOP_MARKER,
    PROVISION_TIMEOUT,
    Approver,
    LiveToolError,
    Session,
    _flag,
    by_name,
    credentials,
    first,
    items,
    mask_secrets,
    payload,
    redact,
)
from .specs import (
    APP_POOL_UPDATE_FIELDS,
    POOL_READ_ONLY_FIELDS,
    Placement,
    desktop_pool_spec,
    farm_spec,
    resolve_placement,
)
from .sweep import run_sweep

DEFAULT_PREFIX = "mcp-e2e-"
_PREFIX_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_HTTP_STATUS = re.compile(r"failed \((\d{3})\)")

PHASES = (
    "Read-only sweep", "Auth & discovery", "Cleanup (leftovers from earlier runs)", "Provision",
    "Reads on the created items", "Desktop pool", "Entitlements", "Machine admin", "Farm & application pool",
    "Config", "User sessions", "Machine power actions", "Teardown", "Refresh & logout",
)

SESSION_TOOLS = ("get_session", "diagnose_session", "get_remote_assistance_ticket", "send_message_to_sessions",
                 "disconnect_sessions", "logoff_sessions", "reset_or_restart_sessions", "end_remote_application")

# Machine / RDS server states that mean provisioning (or the agent) has failed for good.
# Transient ones (AGENT_UNREACHABLE, *_STARTUP_IN_PROGRESS, CUSTOMIZING, ...) are waited out.
MACHINE_FAIL_STATES = {
    "PROVISIONING_ERROR", "ERROR", "AGENT_CONFIG_ERROR", "AGENT_ERROR_DOMAIN_FAILURE", "AGENT_ERROR_INVALID_IP",
    "AGENT_ERROR_PROTOCOL_FAILURE", "BLOCKED_AGENT_VERSION",
    # RDS server spellings (RDSServerMonitorDetailsV3)
    "AGENT_ERR_DOMAIN_FAILURE", "AGENT_ERR_INVALID_IP", "AGENT_ERR_PROTOCOL_FAILURE",
}

# update_settings(general): Horizon returns restricted_client_data entries without a
# "version", then rejects that same data on PUT (verified on 2606).
SETTINGS_QUIRK = ("restricted_client_data.version.unset", "Restricted client version must be set")


# ── Configuration ────────────────────────────────────────────────────────────

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


@dataclass
class Config:
    prefix: str = DEFAULT_PREFIX
    group: str = ""                  # HZ_TEST_GROUP — name or SID
    user: str = ""                   # HZ_TEST_USER — login name (user, DOMAIN\\user, user@domain) or SID
    app_path: str = r"C:\Windows\System32\notepad.exe"
    pool_base_vm_env: str = "HZ_POOL_BASE_VM"
    pool_snapshot_env: str = "HZ_POOL_SNAPSHOT"
    farm_base_vm_env: str = "HZ_FARM_BASE_VM"
    farm_snapshot_env: str = "HZ_FARM_SNAPSHOT"
    wait_for_session: bool = False
    backup: bool = True
    provision_timeout: float = PROVISION_TIMEOUT
    session_timeout: float = 900.0
    session_grace: float = 120.0
    poll_interval: float = 15.0
    base_url: str = ""
    tag: str = field(default_factory=lambda: secrets.token_hex(2))

    @classmethod
    def from_env(cls) -> Config:
        farm_vm, farm_snap = "HZ_FARM_BASE_VM", "HZ_FARM_SNAPSHOT"
        if not (os.environ.get(farm_vm) or os.environ.get(farm_snap)):
            farm_vm, farm_snap = "HZ_BASE_VM", "HZ_SNAPSHOT"  # what test_destructive.py uses
        return cls(
            prefix=os.environ.get("HZ_E2E_PREFIX") or DEFAULT_PREFIX,
            group=os.environ.get("HZ_TEST_GROUP", ""),
            user=os.environ.get("HZ_TEST_USER", ""),
            app_path=os.environ.get("HZ_TEST_APP_PATH") or cls.app_path,
            farm_base_vm_env=farm_vm,
            farm_snapshot_env=farm_snap,
            wait_for_session=_flag("HZ_E2E_WAIT_FOR_SESSION"),
            backup=not _flag("HZ_E2E_SKIP_BACKUP"),
            session_timeout=_env_float("HZ_E2E_SESSION_TIMEOUT", 900.0),
            poll_interval=_env_float("HZ_E2E_POLL_INTERVAL", 15.0),
            base_url=os.environ.get("HZ_BASE_URL", ""),
        )

    def problems(self) -> list[str]:
        """Why this config must not run (empty if it may)."""
        out = []
        if len(self.prefix) < 5 or not _PREFIX_OK.match(self.prefix):
            out.append(f"HZ_E2E_PREFIX {self.prefix!r} must be at least 5 characters of letters, digits, '-' or '_' "
                       "— it is the only thing standing between cleanup and everything else in the pod")
        for var in (self.pool_base_vm_env, self.pool_snapshot_env, self.farm_base_vm_env, self.farm_snapshot_env):
            if not os.environ.get(var):
                alt = {"HZ_BASE_VM": " (or HZ_FARM_BASE_VM)", "HZ_SNAPSHOT": " (or HZ_FARM_SNAPSHOT)"}.get(var, "")
                what = "snapshot taken after the Horizon Agent was installed" if "SNAPSHOT" in var else "base VM"
                out.append(f"{var}{alt} is not set — name or ID of the {what}")
        if not self.group:
            out.append("HZ_TEST_GROUP is not set (AD group name or SID to entitle)")
        if not self.user:
            out.append("HZ_TEST_USER is not set (AD user login name or SID to assign/entitle)")
        return out

    @property
    def pool_name(self) -> str:
        return f"{self.prefix}vdi-{self.tag}"

    @property
    def farm_name(self) -> str:
        return f"{self.prefix}farm-{self.tag}"

    @property
    def app_name(self) -> str:
        return f"{self.prefix}app-{self.tag}"

    # VM names are limited to 15 characters after {n:fixed=2} expands: 4 + 4 + 1 + 2 = 11.
    @property
    def pool_naming_pattern(self) -> str:
        return f"e2ed{self.tag}-{{n:fixed=2}}"

    @property
    def farm_naming_pattern(self) -> str:
        return f"e2er{self.tag}-{{n:fixed=2}}"


# ── Results ──────────────────────────────────────────────────────────────────

def tool_of(label: str) -> str:
    return label.split(" (")[0]


def coverage(rows: list[dict], tools: list[str]) -> dict[str, dict]:
    """One verdict per registered tool from the rows this run recorded.

    FAIL beats everything; then PASS (any successful call), KNOWN, NA, SKIP; a tool with
    no row at all is MISSING.
    """
    out: dict[str, dict] = {}
    for tool in sorted(tools):
        mine = [r for r in rows if tool_of(r["tool"]) == tool]
        by = {s: [r for r in mine if r["status"] == s] for s in ("FAIL", "PASS", "EMPTY", "WARN", "KNOWN", "NA",
                                                                 "SKIP", "INFO")}
        ok = by["PASS"] + by["EMPTY"] + by["WARN"]
        if by["FAIL"]:
            out[tool] = {"status": "FAIL", "detail": by["FAIL"][0]["summary"]}
        elif ok:
            def variants(rs):
                return ", ".join(dict.fromkeys(r["tool"][len(tool):].strip(" ()") or "call" for r in rs))
            na = f"; not applicable here: {variants(by['NA'] + by['KNOWN'])}" if by["NA"] or by["KNOWN"] else ""
            out[tool] = {"status": "PASS", "detail": f"{len(ok)} call(s): {variants(ok)}{na}"[:400]}
        elif by["KNOWN"]:
            out[tool] = {"status": "KNOWN", "detail": by["KNOWN"][0]["summary"]}
        elif by["NA"]:
            out[tool] = {"status": "NA", "detail": by["NA"][0]["summary"]}
        elif by["SKIP"]:
            out[tool] = {"status": "SKIP", "detail": "; ".join(dict.fromkeys(r["summary"] for r in by["SKIP"]))}
        elif by["INFO"]:
            out[tool] = {"status": "FAIL", "detail": f"Only tolerated errors, never a success: {by['INFO'][0]['summary']}"}
        else:
            out[tool] = {"status": "MISSING", "detail": "Never called and not explicitly skipped"}
    return out


@dataclass
class Result:
    coverage: dict[str, dict]
    failures: list[str]
    unexpected_prompts: list[str]
    leftovers: list[str]
    rows: list[dict]
    logged_in: bool = True  # False: login never succeeded, so nothing ran (or was created)

    @property
    def ok(self) -> bool:
        bad = [t for t, v in self.coverage.items() if v["status"] in ("FAIL", "MISSING")]
        return self.logged_in and not (bad or self.failures or self.unexpected_prompts or self.leftovers)

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for v in self.coverage.values():
            counts[v["status"]] = counts.get(v["status"], 0) + 1
        lines = [f"{len(self.coverage)} tools: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))]
        if not self.logged_in:
            lines.append("  horizon_login failed — nothing else was run, and nothing was created or deleted")
        lines += [f"  {v['status']:7} {t}: {v['detail']}" for t, v in sorted(self.coverage.items())
                  if v["status"] == "FAIL" or (v["status"] == "MISSING" and self.logged_in)]
        lines += [f"  failure: {f}" for f in self.failures]
        lines += [f"  unexpected prompt (cancelled): {p.splitlines()[0]}" for p in self.unexpected_prompts]
        if self.leftovers:
            lines.append(f"  MANUAL CLEANUP MAY BE NEEDED: {', '.join(self.leftovers)}")
        return "\n".join(lines)


def http_status(summary: str) -> int | None:
    m = _HTTP_STATUS.search(summary or "")
    return int(m.group(1)) if m else None


def _clean_rejection(code: int | None) -> bool:
    return code is not None and 400 <= code < 500 and code not in (401, 403)


def _eq(field_name: str, value: str) -> str:
    return json.dumps({"type": "Equals", "name": field_name, "value": value})


# ── The flow ─────────────────────────────────────────────────────────────────

_KINDS = {  # kind → (list tool, get tool, delete tool, id argument)
    "app": ("list_application_pools", "get_application_pool", "delete_application_pool", "pool_id"),
    "pool": ("list_desktop_pools", "get_desktop_pool", "delete_desktop_pool", "pool_id"),
    "farm": ("list_rdsh_farms", "get_rdsh_farm", "delete_rdsh_farm", "farm_id"),
}
_KIND_NAMES = {"app": "application pool", "pool": "desktop pool", "farm": "RDS farm"}


class Lifecycle:
    def __init__(self, s: Session, cfg: Config) -> None:
        self.s = s
        self.cfg = cfg
        self.failures: list[str] = []
        self.leftovers: list[str] = []
        self.logged_in = False
        self.login_ok = False                # ever logged in (logged_in goes False again at logout)
        self.pool_placement: Placement | None = None
        self.farm_placement: Placement | None = None
        self.group_id: str | None = None
        self.user_id: str | None = None
        self.created: dict[str, dict] = {}   # kind → {"id", "name"}
        self.machine: dict | None = None     # the pool's (single) machine, once AVAILABLE
        self.machine_error = "the desktop pool was not created"
        self.farm_ready = False
        self.session_restarted = False       # a session action restarted / refreshed the pool's machine
        self._last_progress: dict[str, str] = {}

    # ── plumbing ──

    def phase(self, name: str) -> None:
        self.s.group = f"{PHASES.index(name) + 1:02d} {name}"
        print(f"\n━━ {self.s.group} " + "━" * max(3, 60 - len(self.s.group)))

    def fail(self, msg: str) -> None:
        msg = redact(msg)
        self.failures.append(f"[{self.s.group}] {msg}")
        print(f"  !! {msg}")

    @asynccontextmanager
    async def step(self, what: str):
        """Run one step; a failure is recorded and the flow moves on to the next step."""
        try:
            yield
        except Exception as e:
            self.fail(f"{what}: {e}")

    def expect(self, cond: Any, tool: str, msg: str) -> None:
        if not cond:
            self.s.record(f"{tool} (check)", "FAIL", msg)
            raise LiveToolError(f"{tool}: {msg}")

    def skip(self, tools, reason: str) -> None:
        for t in [tools] if isinstance(tools, str) else tools:
            self.s.skip(t, reason)

    def progress(self, key: str, text: str, elapsed: float) -> None:
        if self._last_progress.get(key) != text:
            self._last_progress[key] = text
            print(f"  …  {elapsed:5.0f}s  {key}: {text}")

    async def probe(self, tool: str, args: dict | None = None) -> tuple[bool, Any, str]:
        """Call a tool without recording a row — for polling loops (a final row is recorded)."""
        try:
            res = await self.s.client.call_tool(tool, args or {}, raise_on_error=False, timeout=CALL_TIMEOUT)
        except Exception as e:
            return False, None, f"{type(e).__name__}: {e}"
        data = mask_secrets(payload(res))
        return not res.is_error, data, str(data)[:500]

    async def probe_resource(self, uri: str) -> Any:
        try:
            contents = await self.s.client.read_resource(uri)
            text = "".join(getattr(c, "text", "") or "" for c in contents)
            return json.loads(text) if text else None
        except Exception:
            return None

    async def wait_until(self, check: Callable[[float], Awaitable[Any]], *, timeout: float, what: str) -> Any:
        t0 = time.monotonic()
        while True:
            elapsed = time.monotonic() - t0
            result = await check(elapsed)
            if result:
                return result
            if elapsed >= timeout:
                raise LiveToolError(f"Timed out after {timeout:.0f}s waiting for {what}")
            await asyncio.sleep(self.cfg.poll_interval)

    async def maybe(self, tool: str, args: dict, *, label: str) -> tuple[bool, Any]:
        """Call an action Horizon may cleanly reject as not applicable here (recorded as NA).
        Returns (applied, data); raises on any other failure."""
        ok, data, summary = await self.s.attempt(tool, args, label=label)
        if ok:
            failed = data.get("failed") if isinstance(data, dict) and data.get("success") is False else None
            if not failed:
                return True, data
            codes = [f.get("status_code") for f in failed if isinstance(f, dict)]
            if not any(isinstance(c, int) and (c >= 500 or c in (401, 403)) for c in codes):
                self.s.mark_last("NA", f"Horizon rejected it here — not applicable: {str(failed)[:300]}")
                return False, data
            self.s.mark_last("FAIL", "bulk action failed")
            raise LiveToolError(f"{label} failed: {failed}")
        if _clean_rejection(http_status(summary)):
            self.s.mark_last("NA", "Horizon rejected it here — not applicable (error recorded)")
            return False, summary
        raise LiveToolError(f"{label} failed: {summary}")

    def bulk_ok(self, res: Any, tool: str) -> None:
        self.expect(isinstance(res, dict) and res.get("success") is True and not res.get("failed"), tool,
                    f"bulk result not a clean success: {str(res)[:300]}")

    async def find(self, kind: str, name: str) -> dict | None:
        ok, data, _ = await self.probe(_KINDS[kind][0], {"filter": _eq("name", name), "size": 100})
        return by_name(data, name) if ok else None

    async def find_prefixed(self, kind: str) -> list[dict]:
        data = await self.s.call(_KINDS[kind][0], {"size": 1000, "fetch_all": True},
                                 label=f"{_KINDS[kind][0]} (find '{self.cfg.prefix}*')")
        return [x for x in items(data) if isinstance(x, dict) and str(x.get("name", "")).startswith(self.cfg.prefix)]

    async def delete(self, kind: str, item: dict, why: str) -> bool:
        """Delete one prefix-named item, retrying while Horizon refuses, then wait until it's gone."""
        list_tool, _, delete_tool, id_arg = _KINDS[kind]
        name, iid = str(item.get("name", "")), item["id"]
        if not name.startswith(self.cfg.prefix):  # the one rule cleanup never breaks
            raise LiveToolError(f"Refusing to delete {name!r}: its name does not start with {self.cfg.prefix!r}")
        self.s.approver.allow(iid)
        requested, last_err = bool(item.get("delete_in_progress")), ""
        t0 = time.monotonic()
        try:
            while True:
                current = await self.find(kind, name)
                elapsed = time.monotonic() - t0
                if current is None:
                    break
                if current.get("delete_in_progress"):
                    requested = True
                    self.progress(name, "delete in progress", elapsed)
                elif not requested:
                    ok, _, summary = await self.s.attempt(delete_tool, {id_arg: iid}, label=f"{delete_tool} ({why})")
                    if ok:
                        requested = True
                        self.s.approver.assert_prompted(iid)
                    elif "Cancelled by the user" in summary:
                        raise LiveToolError(f"{delete_tool} confirmation was cancelled: {summary}")
                    else:
                        last_err = summary
                        self.s.mark_last("INFO", "Horizon refused the delete for now; retrying")
                if elapsed >= self.cfg.provision_timeout:
                    self.s.record(f"{delete_tool} ({why})", "FAIL", f"{name} still present after "
                                  f"{elapsed:.0f}s. Last error: {last_err or 'none'}")
                    raise LiveToolError(f"{_KIND_NAMES[kind]} {name} was not deleted: {last_err or 'timed out'}")
                await asyncio.sleep(self.cfg.poll_interval)
        except Exception:
            self.leftovers.append(f"{_KIND_NAMES[kind]} {name} ({iid})")
            raise
        self.s.record(f"{list_tool} (until {name} is gone)", "PASS", f"gone after {time.monotonic() - t0:.0f}s")
        return True

    async def entitled(self, pool_type: str, pool_id: str, label: str) -> set[str]:
        ok, data, summary = await self.s.attempt("get_pool_entitlement", {"pool_id": pool_id, "pool_type": pool_type},
                                                 label=f"get_pool_entitlement ({pool_type}: {label})")
        if ok:
            return set((data or {}).get("ad_user_or_group_ids") or [])
        if http_status(summary) == 404:  # no entitlements yet may mean no entitlement record
            self.s.mark_last("INFO", "404 read as 'no entitlements'")
            return set()
        raise LiveToolError(f"get_pool_entitlement failed: {summary}")

    async def pool_machines(self) -> list[dict]:
        ok, data, _ = await self.probe("list_machines", {"filter": _eq("desktop_pool_id", self.created["pool"]["id"]),
                                                         "size": 100})
        found = [m for m in items(data) if isinstance(m, dict)] if ok else []
        self.s.approver.allow(*(m["id"] for m in found if m.get("desktop_pool_id") == self.created["pool"]["id"]))
        return found

    async def wait_machine(self, want: str = "AVAILABLE", *, why: str, initial: bool = False,
                           leave_first: bool = False) -> dict:
        """Wait until the pool's machine is in state `want` (default AVAILABLE — Horizon answers a
        misleading 400 to machine actions while it's CUSTOMIZING/PROVISIONING). leave_first
        first gives a just-issued action up to 90s to take the machine out of `want`."""
        pool_id = self.created["pool"]["id"]
        if leave_first:
            async def left(elapsed):
                ms = await self.pool_machines()
                return not any(m.get("state") == want for m in ms) or None
            try:
                await self.wait_until(left, timeout=min(90.0, self.cfg.provision_timeout), what="the action to start")
            except LiveToolError:
                pass  # it may have been quick enough that we never saw it leave

        async def check(elapsed):
            ms = await self.pool_machines()
            self.progress("machine", ", ".join(f"{m.get('name')}={m.get('state')}" for m in ms) or "none yet", elapsed)
            bad = [m for m in ms if m.get("state") in MACHINE_FAIL_STATES]
            if bad:
                raise LiveToolError(f"machine {bad[0].get('name')} went to {bad[0].get('state')}")
            if initial:
                ok, pool, _ = await self.probe("get_desktop_pool", {"pool_id": pool_id})
                st = (pool or {}).get("provisioning_status_data") or {} if ok else {}
                err = st.get("last_provisioning_error") or st.get("instant_clone_pending_image_error")
                if st.get("instant_clone_pending_image_state") == "FAILED" or \
                        st.get("instant_clone_current_image_state") == "FAILED" or \
                        (err and ok and pool.get("enable_provisioning") is False):
                    raise LiveToolError(f"pool provisioning failed: {err or 'image state FAILED'}")
                if err:
                    self.progress("pool", f"last_provisioning_error: {err}", elapsed)
            return first(ms, lambda m: m.get("state") == want)

        t0 = time.monotonic()
        try:
            m = await self.wait_until(check, timeout=self.cfg.provision_timeout, what=f"the machine to be {want}")
        except LiveToolError as e:
            self.s.record(f"list_machines (wait {want}: {why})", "FAIL", str(e))
            raise
        self.s.record(f"list_machines (wait {want}: {why})", "PASS",
                      f"{m.get('name')} {want} after {time.monotonic() - t0:.0f}s")
        self.machine = m
        return m

    # ── phases ──

    async def run(self) -> None:
        try:
            await self.auth_and_discovery()
            if not self.logged_in:
                return
            await self.cleanup_leftovers()
            await self.provision()
            await self.reads()
            await self.desktop_pool()
            await self.entitlements()
            await self.machine_admin()
            await self.farm_and_app()
            await self.config()
            await self.sessions()
            await self.machine_power()
        finally:
            if self.logged_in:
                await self.teardown()
            await self.refresh_and_logout()

    async def auth_and_discovery(self) -> None:
        self.phase(PHASES[1])
        async with self.step("horizon_login"):
            login = await self.s.call("horizon_login", credentials())
            self.logged_in = self.login_ok = True
            self.expect(isinstance(login, dict) and login.get("status") == "authenticated", "horizon_login",
                        f"unexpected login result: {login}")
            self.expect(not {"access_token", "refresh_token"} & set(login), "horizon_login",
                        "login returned full tokens (expected hints only)")
        if not self.logged_in:
            self.fail("Login failed — nothing was created; stopping")
            return
        async with self.step("get_api_coverage"):
            doc = json.dumps(await self.s.call("get_api_coverage"))
            tools = [t.name for t in await self.s.client.list_tools()]
            undocumented = [t for t in tools if t not in doc and t != "get_api_coverage"]
            if undocumented:
                self.s.mark_last("WARN", f"not described by get_api_coverage: {', '.join(undocumented)}")
        async with self.step("desktop pool placement"):
            self.pool_placement = await resolve_placement(self.s, base_vm_env=self.cfg.pool_base_vm_env,
                                                          snapshot_env=self.cfg.pool_snapshot_env)
        async with self.step("farm placement"):
            self.farm_placement = await resolve_placement(self.s, base_vm_env=self.cfg.farm_base_vm_env,
                                                          snapshot_env=self.cfg.farm_snapshot_env)
        async with self.step("HZ_TEST_GROUP"):
            self.group_id = await self.principal(self.cfg.group, group=True)
        async with self.step("HZ_TEST_USER"):
            self.user_id = await self.principal(self.cfg.user, group=False)

    async def principal(self, want: str, *, group: bool) -> str:
        what = "group" if group else "user"
        if want.upper().startswith("S-1-"):
            await self.s.call("get_ad_user_or_group", {"ad_id": want}, label=f"get_ad_user_or_group ({what})")
            return want
        login = want.split("\\")[-1].split("@")[0]
        for field_name, value in (("login_name", login), ("name", want)):
            found = items(await self.s.call("search_ad_users_or_groups", {"filter": _eq(field_name, value), "size": 50},
                                            label=f"search_ad_users_or_groups ({what} by {field_name})"))
            hits = [x for x in found if bool(x.get("group")) == group and value.lower() in
                    (str(x.get("name", "")).lower(), str(x.get("login_name", "")).lower())]
            if len(hits) > 1:
                raise LiveToolError(f"{want!r} matched {len(hits)} AD {what}s — use the SID instead")
            if hits:
                await self.s.call("get_ad_user_or_group", {"ad_id": hits[0]["id"]}, label=f"get_ad_user_or_group ({what})")
                return hits[0]["id"]
        raise LiveToolError(f"AD {what} {want!r} not found")

    async def cleanup_leftovers(self) -> None:
        self.phase(PHASES[2])
        for kind in ("app", "pool", "farm"):  # app pools first: a farm can't go while it publishes apps
            async with self.step(f"find leftover {_KIND_NAMES[kind]}s"):
                found = await self.find_prefixed(kind)
                print(f"  {len(found)} leftover {_KIND_NAMES[kind]}(s): {', '.join(x['name'] for x in found) or '-'}")
                for item in found:
                    async with self.step(f"delete leftover {item['name']}"):
                        await self.delete(kind, item, "leftover")

    async def _create(self, kind: str, tool: str, args: dict, name: str) -> dict | None:
        ok, data, summary = await self.s.attempt(tool, args, timeout=300)
        # Look it up by name even if the tool reported an error, so anything Horizon created
        # anyway is still cleaned up.
        async def appeared(elapsed):
            return await self.find(kind, name)
        try:
            item = await self.wait_until(appeared, timeout=300 if ok else 30, what=f"{name} to appear")
        except LiveToolError:
            if not ok:
                raise LiveToolError(f"{tool} failed: {summary}") from None
            raise
        self.created[kind] = {"id": item["id"], "name": name}
        self.s.approver.allow(item["id"])
        self.expect(ok, tool, f"reported an error but {name} was created: {summary}")
        self.expect(isinstance(data, dict) and data.get("id") == item["id"], tool,
                    f"result should carry the new ID {item['id']}: {data}")
        return item

    async def provision(self) -> None:
        self.phase(PHASES[3])
        cfg = self.cfg
        desc = "Temporary item created by the horizon-mcp end-to-end test. Safe to delete."
        if self.pool_placement:
            async with self.step("create_desktop_pool"):
                spec = desktop_pool_spec(self.pool_placement, cfg.pool_name, cfg.pool_naming_pattern, desc)
                await self._create("pool", "create_desktop_pool", {"spec": spec}, cfg.pool_name)
        else:
            self.skip("create_desktop_pool", "Desktop pool placement could not be resolved (see Auth & discovery)")
        if self.farm_placement:
            async with self.step("create_rdsh_farm"):
                spec = farm_spec(self.farm_placement, cfg.farm_name, cfg.farm_naming_pattern, desc)
                await self._create("farm", "create_rdsh_farm", {"spec": spec}, cfg.farm_name)
        else:
            self.skip("create_rdsh_farm", "Farm placement could not be resolved (see Auth & discovery)")

        if "pool" in self.created:
            print(f"  waiting up to {cfg.provision_timeout:.0f}s for {cfg.pool_name}'s machine…")
            try:
                await self.wait_machine(why="provisioned", initial=True)
            except Exception as e:
                self.machine_error = f"the pool's machine never became AVAILABLE: {redact(str(e))}"
                self.fail(self.machine_error)
        if "farm" in self.created:
            print(f"  waiting up to {cfg.provision_timeout:.0f}s for {cfg.farm_name}'s RDS server…")
            async with self.step("RDS server provisioning"):
                await self.wait_rds_server()
                self.farm_ready = True

        if "farm" in self.created:
            async with self.step("create_application_pool"):
                await self._create("app", "create_application_pool", {
                    "name": cfg.app_name, "farm_id": self.created["farm"]["id"],
                    "executable_path": cfg.app_path, "display_name": cfg.app_name,
                }, cfg.app_name)
        else:
            self.skip("create_application_pool", "The farm was not created")

    async def wait_rds_server(self) -> None:
        farm_id = self.created["farm"]["id"]

        async def check(elapsed):
            ok, farm, _ = await self.probe("get_rdsh_farm", {"farm_id": farm_id})
            afs = (farm or {}).get("automated_farm_settings") or {} if ok else {}
            st = afs.get("provisioning_status_data") or {}
            err = st.get("last_provisioning_error") or st.get("instant_clone_pending_image_error")
            if st.get("instant_clone_pending_image_state") == "FAILED" or \
                    st.get("instant_clone_current_image_state") == "FAILED" or \
                    (err and afs.get("enable_provisioning") is False):
                raise LiveToolError(f"farm provisioning failed: {err or 'image state FAILED'}")
            servers = [x for x in items(await self.probe_resource("horizon://monitor/rds-servers") or [])
                       if isinstance(x, dict) and x.get("farm_id") == farm_id]
            states = {x.get("name"): (x.get("details_v3") or x.get("details") or {}).get("state") or x.get("status")
                      for x in servers}
            self.progress("rds server", ", ".join(f"{n}={s}" for n, s in states.items()) or
                          (f"none yet ({err})" if err else "none yet"), elapsed)
            bad = [n for n, s in states.items() if s in MACHINE_FAIL_STATES]
            if bad:
                raise LiveToolError(f"RDS server {bad[0]} went to {states[bad[0]]}")
            return any(s == "AVAILABLE" for s in states.values())

        t0 = time.monotonic()
        try:
            await self.wait_until(check, timeout=self.cfg.provision_timeout, what="the farm's RDS server to be AVAILABLE")
        except LiveToolError as e:
            self.s.record("get_rdsh_farm (wait for RDS server)", "FAIL", str(e))
            raise
        self.s.record("get_rdsh_farm (wait for RDS server)", "PASS",
                      f"RDS server AVAILABLE after {time.monotonic() - t0:.0f}s (horizon://monitor/rds-servers)")

    async def reads(self) -> None:
        self.phase(PHASES[4])
        pool, farm, app = (self.created.get(k) for k in ("pool", "farm", "app"))
        if pool:
            async with self.step("desktop pool reads"):
                listed = await self.s.call("list_desktop_pools", {"filter": _eq("name", pool["name"])},
                                           label="list_desktop_pools (by name)")
                self.expect(isinstance(listed, dict) and {"items", "has_more", "next_page"} <= set(listed),
                            "list_desktop_pools", "not a paginated {items, has_more, next_page} result")
                self.expect(by_name(listed, pool["name"]), "list_desktop_pools", "the new pool is not listed")
                got = await self.s.call("get_desktop_pool", {"pool_id": pool["id"]})
                self.expect(got.get("name") == pool["name"] and got.get("user_assignment") == "DEDICATED" and
                            got.get("source") == "INSTANT_CLONE", "get_desktop_pool", f"unexpected pool: {str(got)[:300]}")
                max_machines = (got.get("pattern_naming_settings") or {}).get("max_number_of_machines")
                self.expect(max_machines == 1, "get_desktop_pool", f"max_number_of_machines is {max_machines}, not 1")
            async with self.step("machine reads"):
                ms = items(await self.s.call("list_machines", {"filter": _eq("desktop_pool_id", pool["id"])},
                                             label="list_machines (in the pool)"))
                self.expect(len(ms) == 1, "list_machines", f"expected exactly 1 machine in the pool, found {len(ms)}")
                m = await self.s.call("get_machine", {"machine_id": ms[0]["id"]})
                self.expect(m.get("desktop_pool_id") == pool["id"], "get_machine", "machine is not in the test pool")
            async with self.step("list_sessions"):
                await self.s.call("list_sessions", {"filter": _eq("desktop_pool_id", pool["id"])},
                                  label="list_sessions (in the pool)")
        else:
            self.skip(["list_desktop_pools (by name)", "get_desktop_pool", "list_machines (in the pool)", "get_machine",
                       "list_sessions (in the pool)"], "The desktop pool was not created")
        if farm:
            async with self.step("farm reads"):
                listed = await self.s.call("list_rdsh_farms", {"filter": _eq("name", farm["name"])},
                                           label="list_rdsh_farms (by name)")
                self.expect(by_name(listed, farm["name"]), "list_rdsh_farms", "the new farm is not listed")
                got = await self.s.call("get_rdsh_farm", {"farm_id": farm["id"]})
                self.expect(got.get("name") == farm["name"], "get_rdsh_farm", "wrong farm returned")
                health = await self.s.call("get_infrastructure_health", {"components": ["farms"]},
                                           label="get_infrastructure_health (farms)")
                self.expect(first((health or {}).get("farms"), lambda f: f.get("id") == farm["id"]),
                            "get_infrastructure_health", "the new farm is missing from farm health")
        else:
            self.skip(["list_rdsh_farms (by name)", "get_rdsh_farm", "get_infrastructure_health (farms)"],
                      "The farm was not created")
        if app:
            async with self.step("application pool reads"):
                listed = await self.s.call("list_application_pools", {"filter": _eq("name", app["name"])},
                                           label="list_application_pools (by name)")
                self.expect(by_name(listed, app["name"]), "list_application_pools", "the new app pool is not listed")
                got = await self.s.call("get_application_pool", {"pool_id": app["id"]})
                self.expect(got.get("farm_id") == farm["id"] if farm else True, "get_application_pool", "wrong farm")
                self.expect(str(got.get("executable_path", "")).lower() == self.cfg.app_path.lower(),
                            "get_application_pool", f"executable_path is {got.get('executable_path')!r}")
        else:
            self.skip(["list_application_pools (by name)", "get_application_pool"], "The application pool was not created")
        async with self.step("get_metrics"):
            await self.s.call("get_metrics", {"scope": ["pools", "machines", "rds_servers"]},
                              label="get_metrics (pools, machines, rds_servers)")
        async with self.step("audit events"):
            edb = await self.s.call("get_event_database")
            if isinstance(edb, dict) and edb.get("event_database_configured") is False:
                self.skip("list_audit_events", "No event database is configured (Horizon answers 409)")
            else:
                await self.s.call("list_audit_events", {"size": 25})

    async def desktop_pool(self) -> None:
        self.phase(PHASES[5])
        pool = self.created.get("pool")
        if not pool:
            self.skip(["update_desktop_pool", "desktop_pool_action"], "The desktop pool was not created")
            return
        pid = pool["id"]
        async with self.step("update_desktop_pool"):
            got = await self.s.call("get_desktop_pool", {"pool_id": pid}, label="get_desktop_pool (before update)")
            spec = {k: v for k, v in got.items() if k not in POOL_READ_ONLY_FIELDS}
            original = got.get("display_name")
            renamed = f"{pool['name']} renamed"
            try:
                await self.s.call("update_desktop_pool", {"pool_id": pid, "spec": {**spec, "display_name": renamed}},
                                  label="update_desktop_pool (rename)")
                now = await self.s.call("get_desktop_pool", {"pool_id": pid}, label="get_desktop_pool (renamed)")
                self.expect(now.get("display_name") == renamed, "update_desktop_pool", "display_name did not change")
            finally:
                await self.s.call("update_desktop_pool", {"pool_id": pid, "spec": spec}, label="update_desktop_pool (restore)")
            now = await self.s.call("get_desktop_pool", {"pool_id": pid}, label="get_desktop_pool (restored)")
            self.expect(now.get("display_name") == original, "update_desktop_pool", "display_name was not restored")
        for action, key, want in (("disable", "enabled", False), ("enable", "enabled", True),
                                  ("disable-provisioning", "enable_provisioning", False),
                                  ("enable-provisioning", "enable_provisioning", True)):
            async with self.step(f"desktop_pool_action {action}"):
                res = await self.s.call("desktop_pool_action", {"pool_ids": [pid], "action": action},
                                        label=f"desktop_pool_action ({action})")
                self.bulk_ok(res, "desktop_pool_action")
                if action.startswith("disable"):
                    self.s.approver.assert_prompted(pid)
                now = await self.s.call("get_desktop_pool", {"pool_id": pid}, label=f"get_desktop_pool (after {action})")
                self.expect(now.get(key) is want, "desktop_pool_action", f"{key} is {now.get(key)!r} after {action}")

    async def entitlements(self) -> None:
        self.phase(PHASES[6])
        pool, app = self.created.get("pool"), self.created.get("app")
        if not (self.group_id and self.user_id):
            self.skip(["set_pool_entitlements", "list_pool_entitlements", "get_pool_entitlement"],
                      "HZ_TEST_GROUP / HZ_TEST_USER could not be resolved")
            return
        g, u = self.group_id, self.user_id
        if pool:
            pid = pool["id"]
            async with self.step("desktop pool entitlements"):
                self.expect(g not in await self.entitled("desktop", pid, "before"), "get_pool_entitlement",
                            "group already entitled to a brand-new pool")
                args = {"pool_id": pid, "pool_type": "desktop"}
                self.bulk_ok(await self.s.call("set_pool_entitlements", {**args, "action": "add",
                                                                          "ad_user_or_group_ids": [g]},
                                               label="set_pool_entitlements (desktop add group)"), "set_pool_entitlements")
                self.expect(g in await self.entitled("desktop", pid, "after add"), "set_pool_entitlements",
                            "group not entitled after add")
                listed = await self.s.call("list_pool_entitlements", {"pool_type": "desktop"},
                                           label="list_pool_entitlements (desktop)")
                entry = first(listed, lambda e: e.get("id") == pid) or {}
                self.expect(g in (entry.get("ad_user_or_group_ids") or []), "list_pool_entitlements",
                            "the new entitlement is not listed")
                self.bulk_ok(await self.s.call("set_pool_entitlements", {**args, "action": "replace",
                                                                          "ad_user_or_group_ids": [u]},
                                               label="set_pool_entitlements (desktop replace with user)"),
                             "set_pool_entitlements")
                self.s.approver.assert_prompted(pid)
                now = await self.entitled("desktop", pid, "after replace")
                self.expect(u in now and g not in now, "set_pool_entitlements", f"after replace: {sorted(now)}")
                self.bulk_ok(await self.s.call("set_pool_entitlements", {**args, "action": "remove",
                                                                          "ad_user_or_group_ids": [u]},
                                               label="set_pool_entitlements (desktop remove user)"),
                             "set_pool_entitlements")
                self.expect(u not in await self.entitled("desktop", pid, "after remove"), "set_pool_entitlements",
                            "user still entitled after remove")
        else:
            self.skip("set_pool_entitlements (desktop)", "The desktop pool was not created")
        if app:
            aid = app["id"]
            async with self.step("application pool entitlements"):
                args = {"pool_id": aid, "pool_type": "application", "ad_user_or_group_ids": [g]}
                self.bulk_ok(await self.s.call("set_pool_entitlements", {**args, "action": "add"},
                                               label="set_pool_entitlements (application add group)"),
                             "set_pool_entitlements")
                self.expect(g in await self.entitled("application", aid, "after add"), "set_pool_entitlements",
                            "group not entitled after add")
                listed = await self.s.call("list_pool_entitlements", {"pool_type": "application"},
                                           label="list_pool_entitlements (application)")
                entry = first(listed, lambda e: e.get("id") == aid) or {}
                self.expect(g in (entry.get("ad_user_or_group_ids") or []), "list_pool_entitlements",
                            "the new entitlement is not listed")
                self.bulk_ok(await self.s.call("set_pool_entitlements", {**args, "action": "remove"},
                                               label="set_pool_entitlements (application remove group)"),
                             "set_pool_entitlements")
                self.s.approver.assert_prompted(aid)
                self.expect(g not in await self.entitled("application", aid, "after remove"), "set_pool_entitlements",
                            "group still entitled after remove")
        else:
            self.skip("set_pool_entitlements (application)", "The application pool was not created")

    async def machine_admin(self) -> None:
        self.phase(PHASES[7])
        if not self.machine:
            self.skip(["assign_machine_users", "machine_action (enter_maintenance)", "machine_action (exit_maintenance)"],
                      f"No AVAILABLE machine: {self.machine_error}")
            return
        if self.user_id:
            async with self.step("assign_machine_users"):
                mid, u = self.machine["id"], self.user_id
                for action, present in (("assign", True), ("unassign", False)):
                    res = await self.s.call("assign_machine_users", {"machine_id": mid, "user_ids": [u], "action": action},
                                            label=f"assign_machine_users ({action})")
                    self.bulk_ok(res, "assign_machine_users")
                    m = await self.s.call("get_machine", {"machine_id": mid}, label=f"get_machine (after {action})")
                    self.expect((u in (m.get("user_ids") or [])) is present, "assign_machine_users",
                                f"user_ids after {action}: {m.get('user_ids')}")
        else:
            self.skip("assign_machine_users", "HZ_TEST_USER could not be resolved")
        async with self.step("maintenance mode"):
            await self.machine_action("enter_maintenance", strict=True)
            await self.wait_machine("MAINTENANCE", why="entered maintenance")
            await self.machine_action("exit_maintenance", strict=True)
            await self.wait_machine(why="exited maintenance")

    async def machine_action(self, action: str, *, strict: bool) -> bool:
        mid = self.machine["id"] if self.machine else ""
        args = {"machine_ids": [mid], "action": action}
        if strict:
            res = await self.s.call("machine_action", args, label=f"machine_action ({action})")
            self.bulk_ok(res, "machine_action")
            applied = True
        else:
            applied, _ = await self.maybe("machine_action", args, label=f"machine_action ({action})")
        if applied and action in ("shutdown", "restart", "reset", "rebuild", "archive"):
            self.s.approver.assert_prompted(mid)
        return applied

    async def farm_and_app(self) -> None:
        self.phase(PHASES[8])
        farm, app = self.created.get("farm"), self.created.get("app")
        if farm:
            fid = farm["id"]
            async with self.step("update_rdsh_farm (no-op)"):
                before = await self.s.call("get_rdsh_farm", {"farm_id": fid}, label="get_rdsh_farm (before update)")
                spec = {k: v for k, v in before.items() if k in _FARM_UPDATE_FIELDS}
                await self.s.call("update_rdsh_farm", {"farm_id": fid, "spec": spec}, label="update_rdsh_farm (no-op)")
                after = await self.s.call("get_rdsh_farm", {"farm_id": fid}, label="get_rdsh_farm (after update)")
                # automated_farm_settings carries live provisioning status, so it may move on its own.
                drift = sorted(k for k in _FARM_UPDATE_FIELDS - {"automated_farm_settings"}
                               if before.get(k) != after.get(k))
                self.expect(not drift, "update_rdsh_farm", f"fields changed by a no-op update: {drift}")
            for action, want in (("disable", False), ("enable", True)):
                async with self.step(f"rdsh_farm_action {action}"):
                    res = await self.s.call("rdsh_farm_action", {"farm_ids": [fid], "action": action},
                                            label=f"rdsh_farm_action ({action})")
                    self.expect(res.get("succeeded") == 1 and not res.get("errors"), "rdsh_farm_action", str(res))
                    if action == "disable":
                        self.s.approver.assert_prompted(fid)
                    now = await self.s.call("get_rdsh_farm", {"farm_id": fid}, label=f"get_rdsh_farm (after {action})")
                    self.expect(now.get("enabled") is want, "rdsh_farm_action", f"enabled is {now.get('enabled')!r}")
        else:
            self.skip(["update_rdsh_farm", "rdsh_farm_action"], "The farm was not created")
        if app:
            aid = app["id"]
            async with self.step("update_application_pool"):
                got = await self.s.call("get_application_pool", {"pool_id": aid}, label="get_application_pool (before)")
                spec = {k: v for k, v in got.items() if k in APP_POOL_UPDATE_FIELDS}
                renamed = f"{app['name']}-renamed"
                try:
                    await self.s.call("update_application_pool",
                                      {"pool_id": aid, "spec": {**spec, "display_name": renamed}},
                                      label="update_application_pool (rename)")
                    now = await self.s.call("get_application_pool", {"pool_id": aid}, label="get_application_pool (renamed)")
                    self.expect(now.get("display_name") == renamed, "update_application_pool", "display_name unchanged")
                finally:
                    await self.s.call("update_application_pool", {"pool_id": aid, "spec": spec},
                                      label="update_application_pool (restore)")
                now = await self.s.call("get_application_pool", {"pool_id": aid}, label="get_application_pool (restored)")
                drift = sorted(k for k in APP_POOL_UPDATE_FIELDS if got.get(k) != now.get(k))
                self.expect(not drift, "update_application_pool", f"fields differ after the round trip: {drift}")
        else:
            self.skip("update_application_pool", "The application pool was not created")

    async def _noop_round_trip(self, tool: str, prefix: str, read, write, known: tuple[str, ...] = ()) -> None:
        """Write back exactly what was read; the server must report and keep no change."""
        approver = self.s.approver
        approver.allow_noop(prefix)
        before = await read("before")
        try:
            ok, _, summary = await write(before, "no-op")
            if ok:
                self.expect(any(a and NOOP_MARKER in m for a, m in approver.seen), tool,
                            "the confirmation prompt did not say that nothing changes")
            elif any(k in summary for k in known):
                self.s.mark_last("KNOWN", "Known Horizon quirk: it rejects its own GET output")
            else:
                raise LiveToolError(f"{tool} failed: {summary}")
            after = await read("after")
            self.expect(after == before, tool, "values changed after writing back an identical object")
        finally:
            current = await read("final")
            if current != before:  # put the original back — the only non-no-op write allowed
                approver.allow_restore(prefix)
                await write(before, "restore")

    async def config(self) -> None:
        self.phase(PHASES[9])
        async with self.step("update_global_policies (no-op)"):
            async def read_p(tag):
                return await self.s.call("get_global_policies", label=f"get_global_policies ({tag})")

            async def write_p(spec, tag):
                return await self.s.attempt("update_global_policies", {"spec": spec}, label=f"update_global_policies ({tag})")

            await self._noop_round_trip("update_global_policies", "Change Horizon global policies", read_p, write_p)
        async with self.step("update_settings general (no-op)"):
            async def read_s(tag):
                return await self.s.read_json_resource("horizon://config/settings/general")

            async def write_s(spec, tag):
                return await self.s.attempt("update_settings", {"setting_type": "general", "spec": spec},
                                            label=f"update_settings (general {tag})")

            await self._noop_round_trip("update_settings", "Change Horizon general settings", read_s, write_s,
                                        known=SETTINGS_QUIRK)
        if not self.cfg.backup:
            self.skip("trigger_connection_server_backup", "Skipped: HZ_E2E_SKIP_BACKUP=1")
            return
        async with self.step("trigger_connection_server_backup"):
            cs = first(await self.s.call("list_connection_servers", label="list_connection_servers (for backup)"))
            if not cs:
                raise LiveToolError("no connection server to back up")
            res = await self.s.call("trigger_connection_server_backup", {"server_ids": [cs["id"]]},
                                    label="trigger_connection_server_backup (one server)")
            self.bulk_ok(res, "trigger_connection_server_backup")

    # ── sessions ──

    async def sessions(self) -> None:
        self.phase(PHASES[10])
        if not self.cfg.wait_for_session:
            self.skip(SESSION_TOOLS, "Needs a real user session — set HZ_E2E_WAIT_FOR_SESSION=1 and connect as "
                                     "HZ_TEST_USER when prompted")
            return
        pool, app = self.created.get("pool"), self.created.get("app")
        targets = []
        if pool and self.machine:
            targets.append(("desktop", pool))
        if app and self.farm_ready:
            targets.append(("application", app))
        if not (targets and self.user_id):
            self.skip(SESSION_TOOLS, "Nothing a user could connect to (no AVAILABLE machine / RDS server, "
                                     "or HZ_TEST_USER unresolved)")
            return
        async with self.step("entitle HZ_TEST_USER"):
            for pool_type, item in targets:
                res = await self.s.call("set_pool_entitlements", {"pool_id": item["id"], "pool_type": pool_type,
                                                                  "action": "add", "ad_user_or_group_ids": [self.user_id]},
                                        label=f"set_pool_entitlements ({pool_type} add session user)")
                self.bulk_ok(res, "set_pool_entitlements")
        found = await self.wait_for_sessions(targets)
        if not found:
            self.skip(SESSION_TOOLS, f"No session on the test pool/farm within {self.cfg.session_timeout:.0f}s")
            return
        desk, appses = found.get("DESKTOP"), found.get("APPLICATION")
        primary = desk or appses
        second = appses if desk and appses else None
        assert primary is not None
        for ses in (desk, appses):
            if ses:
                sid = ses["id"]
                async with self.step(f"read {ses['session_type']} session"):
                    got = await self.s.call("get_session", {"session_id": sid},
                                            label=f"get_session ({ses['session_type'].lower()})")
                    self.expect(got.get("id") == sid, "get_session", "wrong session returned")
                    await self.s.call("diagnose_session", {"session_id": sid},
                                      label=f"diagnose_session ({ses['session_type'].lower()})")
        pid = primary["id"]
        async with self.step("get_remote_assistance_ticket"):
            t = await self.s.call("get_remote_assistance_ticket", {"session_id": pid})
            self.expect(isinstance(t, dict) and t.get("ticket"), "get_remote_assistance_ticket", "no ticket returned")
        async with self.step("send_message_to_sessions"):
            res = await self.s.call("send_message_to_sessions", {
                "session_ids": [pid], "message": "horizon-mcp end-to-end test: this is only a test message.",
                "message_type": "INFO"})
            self.bulk_ok(res, "send_message_to_sessions")

        app_target = second or (primary if primary is appses else None)
        if app_target:
            async with self.step("end_remote_application"):
                await self.end_remote_app(app_target["id"])
            if second:
                async with self.step("logoff_sessions (application session)"):
                    await self.logoff(second["id"], "application")
        else:
            self.skip("end_remote_application", "No application session — launch the test app as well")

        async with self.step("disconnect_sessions"):
            res = await self.s.call("disconnect_sessions", {"session_ids": [pid]})
            self.bulk_ok(res, "disconnect_sessions")
            self.s.approver.assert_prompted(pid)

            async def disconnected(elapsed):
                ok, s, _ = await self.probe("get_session", {"session_id": pid})
                return ok and (s or {}).get("session_state") == "DISCONNECTED"
            await self.wait_until(disconnected, timeout=180, what="the session to show DISCONNECTED")
            self.s.record("get_session (after disconnect)", "PASS", "session_state DISCONNECTED")
        if second:  # two sessions: the application one was logged off, so restart the desktop's machine
            async with self.step("reset_or_restart_sessions"):
                res = await self.s.call("reset_or_restart_sessions", {"session_ids": [pid], "action": "restart"},
                                        label="reset_or_restart_sessions (restart desktop)")
                self.bulk_ok(res, "reset_or_restart_sessions")
                self.s.approver.assert_prompted(pid)
                self.session_restarted = primary is desk
        else:
            async with self.step("logoff_sessions"):
                await self.logoff(pid, primary["session_type"].lower())
                self.session_restarted = primary is desk  # an instant clone may be refreshed on logoff
            self.skip("reset_or_restart_sessions", "Needs a second session — open both the desktop and the app, "
                                                   "so one can be logged off and the other restarted")

    async def wait_for_sessions(self, targets: list[tuple[str, dict]]) -> dict[str, dict]:
        # A desktop session carries desktop_pool_id; an application session carries the farm's ID.
        ids = {item["id"] if t == "desktop" else self.created["farm"]["id"] for t, item in targets}
        what = "\n".join(f"      • {'desktop' if t == 'desktop' else 'application'}  {item['name']}" for t, item in targets)
        print("\n  ┌─ ACTION NEEDED ──────────────────────────────────────────────")
        print(f"  │ Sign in with Horizon Client or HTML Access{' at ' + self.cfg.base_url if self.cfg.base_url else ''}")
        print(f"  │ as {self.cfg.user} and open{' BOTH' if len(targets) > 1 else ''}:")
        print("\n".join(f"  │{line}" for line in what.splitlines()))
        print(f"  │ Waiting up to {self.cfg.session_timeout:.0f}s. Leave the sessions open — the test disconnects,")
        print("  │ logs off and restarts them itself.")
        print("  └──────────────────────────────────────────────────────────────")
        found: dict[str, dict] = {}
        t_first: list[float] = []

        async def check(elapsed):
            ok, data, _ = await self.probe("list_sessions", {"size": 1000})
            for ses in items(data) if ok else []:
                if ses.get("desktop_pool_id") in ids or ses.get("farm_id") in ids:
                    kind = ses.get("session_type") or ("DESKTOP" if ses.get("desktop_pool_id") in ids else "APPLICATION")
                    if kind not in found:
                        found[kind] = {**ses, "session_type": kind}
                        self.s.approver.allow(ses["id"])
                        print(f"  ✓ {kind.lower()} session {ses['id']} ({ses.get('session_state')})")
            if found and not t_first:
                t_first.append(elapsed)
            if len(found) >= len(targets):
                return True
            if t_first and elapsed - t_first[0] >= self.cfg.session_grace:
                return True  # carry on with what we have
            self.progress("sessions", ", ".join(found) or "waiting", elapsed)
            return False

        try:
            await self.wait_until(check, timeout=self.cfg.session_timeout, what="a user session")
        except LiveToolError:
            pass
        self.s.record("list_sessions (wait for a user)", "PASS" if found else "SKIP",
                      f"found: {', '.join(found) or 'nothing'}")
        return found

    async def end_remote_app(self, sid: str) -> None:
        diag = await self.s.call("diagnose_session", {"session_id": sid, "aspects": ["remote_applications"]},
                                 label="diagnose_session (remote_applications)")
        apps = (diag or {}).get("remote_applications")
        target = first(apps if isinstance(apps, list) else [], lambda a: a.get("remote_application_id"))
        if not target:
            self.skip("end_remote_application", f"diagnose_session found no running remote application: {str(apps)[:200]}")
            return
        await self.s.call("end_remote_application", {"session_id": sid,
                                                     "remote_application_id": target["remote_application_id"]})
        self.s.approver.assert_prompted(sid)

    async def logoff(self, sid: str, kind: str) -> None:
        res = await self.s.call("logoff_sessions", {"session_ids": [sid], "forced": True},
                                label=f"logoff_sessions ({kind})")
        self.bulk_ok(res, "logoff_sessions")
        self.s.approver.assert_prompted(sid)

        async def gone(elapsed):
            ok, _, summary = await self.probe("get_session", {"session_id": sid})
            return not ok and http_status(summary) == 404
        await self.wait_until(gone, timeout=180, what="the session to end")
        self.s.record(f"get_session (after logoff: {kind})", "PASS", "session gone (404)")

    # ── machine power actions ──

    async def machine_power(self) -> None:
        self.phase(PHASES[11])
        labels = [f"machine_action ({a})" for a in ("restart", "reset", "recover", "rebuild", "archive", "shutdown")]
        if not self.machine:
            self.skip(labels, f"No AVAILABLE machine: {self.machine_error}")
            return
        try:
            await self.wait_machine(why="before power actions", leave_first=self.session_restarted)
        except Exception as e:
            self.fail(f"machine not AVAILABLE before power actions: {e}")
            self.skip(labels, "The machine did not return to AVAILABLE")
            return
        # Most reversible first; shutdown last, since nothing clean brings an instant clone back
        # except Horizon itself — the pool is deleted right after anyway.
        plan = (("restart", True), ("reset", True), ("recover", False), ("rebuild", False), ("archive", False),
                ("shutdown", False))
        for i, (action, strict) in enumerate(plan):
            try:
                applied = await self.machine_action(action, strict=strict)
                if applied and action != "shutdown":
                    await self.wait_machine(why=f"after {action}", leave_first=action != "recover")
            except Exception as e:
                self.fail(f"machine_action {action}: {e}")
                self.skip(labels[i + 1:], f"Stopped after machine_action ({action}) failed")
                return

    # ── teardown ──

    async def teardown(self) -> None:
        self.phase(PHASES[12])
        cfg = self.cfg
        for kind, name in (("app", cfg.app_name), ("pool", cfg.pool_name), ("farm", cfg.farm_name)):
            async with self.step(f"delete {name}"):
                item = self.created.get(kind) or await self.find(kind, name)
                if item:
                    await self.delete(kind, item, "teardown")
        async with self.step("verify nothing is left"):
            for kind in ("app", "pool", "farm"):
                ours = [x for x in await self.find_prefixed(kind) if x["name"].endswith(f"-{cfg.tag}")]
                self.leftovers += [f"{_KIND_NAMES[kind]} {x['name']} ({x['id']})" for x in ours
                                   if not any(x["name"] in lo for lo in self.leftovers)]
        if self.leftovers:
            print(f"\n  !! MANUAL CLEANUP MAY BE NEEDED: {', '.join(self.leftovers)}")

    async def refresh_and_logout(self) -> None:
        self.phase(PHASES[13])
        if not self.logged_in:
            self.skip(["horizon_refresh_token", "horizon_logout"], "Never logged in")
            return
        async with self.step("horizon_refresh_token"):
            res = await self.s.call("horizon_refresh_token")
            self.expect(isinstance(res, dict) and res.get("status") == "token_refreshed", "horizon_refresh_token", str(res))
            await self.s.call("list_connection_servers", label="list_connection_servers (with the refreshed token)")
        async with self.step("horizon_logout"):
            res = await self.s.call("horizon_logout")
            self.expect(isinstance(res, dict) and res.get("logged_out") is True, "horizon_logout", str(res))
            self.logged_in = False
            ok, _, _ = await self.s.attempt("list_connection_servers", label="list_connection_servers (after logout)")
            if ok:
                self.s.mark_last("FAIL", "a call still worked after logout")
                raise LiveToolError("a call still worked after horizon_logout")
            self.s.mark_last("INFO", "refused after logout, as expected")


# ── Running it ───────────────────────────────────────────────────────────────

class _SweepRunner:
    """sweep.Runner over a Session, with phase-prefixed sections and the lab's known gaps."""

    def __init__(self, s: Session, prefix: str) -> None:
        self.s = s
        self.prefix = prefix

    async def call(self, tool, args=None, label=None):
        ok, data, summary = await self.s.attempt(tool, args, label=label)
        if not ok and tool == "list_audit_events" and http_status(summary) == 409:
            self.s.mark_last("SKIP", "No event database is configured (Horizon answers 409)")
        elif not ok and tool == "get_pool_entitlement" and http_status(summary) == 404:
            self.s.mark_last("INFO", "404: the pool it picked has no entitlements")
        return data if ok else None

    def skip(self, label, reason):
        self.s.skip(label, reason)

    def section(self, name):
        self.s.group = f"{self.prefix} · {name}"


Opener = Callable[[str, Approver], AbstractAsyncContextManager[Session]]


async def run_e2e(open_session: Opener, cfg: Config, *, rows: list[dict], prompts: list[dict] | None = None) -> Result:
    """The whole run: sweep (own server process), then the lifecycle flow (another one)."""
    start = len(rows)
    failures: list[str] = []
    sweep_approver = Approver(prompts=prompts)  # read-only: allows nothing
    approver = Approver(prompts=prompts)
    tools: list[str] = []
    group = f"01 {PHASES[0]}"
    print(f"\n━━ {group} " + "━" * (60 - len(group)))
    try:
        async with open_session(group, sweep_approver) as ss:
            await run_sweep(_SweepRunner(ss, group))
    except Exception as e:
        failures.append(f"[{group}] {redact(f'{type(e).__name__}: {e}')}")
    flow = None
    try:
        async with open_session(f"02 {PHASES[1]}", approver) as s:
            tools = [t.name for t in await s.client.list_tools()]
            flow = Lifecycle(s, cfg)
            await flow.run()
    except Exception as e:
        failures.append(f"[lifecycle] {redact(f'{type(e).__name__}: {e}')}")
    mine = rows[start:]
    if flow:
        failures = failures + flow.failures
    unexpected = sweep_approver.unexpected() + approver.unexpected()
    return Result(coverage=coverage(mine, tools) if tools else {}, failures=failures,
                  unexpected_prompts=[redact(p) for p in unexpected],
                  leftovers=flow.leftovers if flow else [], rows=mine, logged_in=bool(flow and flow.login_ok))


def format_coverage(result: Result) -> str:
    width = max((len(t) for t in result.coverage), default=10)
    return "\n".join(f"  {v['status']:7} {t:{width}}  {v['detail'][:110]}" for t, v in sorted(result.coverage.items()))


def format_plan(result: Result) -> str:
    """Every phase and the tool calls in it, in order."""
    out, group = [], None
    for r in result.rows:
        if r["group"] != group:
            group = r["group"]
            out.append(f"\n{group}")
        out.append(f"    {r['status']:5} {r['tool']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import contextlib
    import io

    from .fake_horizon import run_offline

    ap = argparse.ArgumentParser(prog="python -m tests.live.lifecycle",
                                 description="Plan / dry run of the end-to-end lifecycle test against an offline "
                                             "fake Horizon. Nothing is contacted.")
    ap.add_argument("--plan", action="store_true", help="print every phase and tool call, then the coverage table")
    ap.add_argument("--no-session", action="store_true", help="plan without HZ_E2E_WAIT_FOR_SESSION")
    ap.add_argument("-v", "--verbose", action="store_true", help="show the flow's own progress output too")
    args = ap.parse_args(argv)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf) if not args.verbose else contextlib.nullcontext():
        result, _ = run_offline(wait_for_session=not args.no_session)
    print("Dry run against an offline fake Horizon — statuses are the fake's answers, not your lab's.")
    print(format_plan(result))
    print("\nCoverage of the registered tools:")
    print(format_coverage(result))
    print("\n" + result.summary())
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
