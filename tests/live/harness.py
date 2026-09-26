"""Shared plumbing for the live integration suite.

Spawns the real server over MCP stdio (the way Claude Desktop / Code run it), logs in
with credentials from HZ_* env vars, and records every call so the optional HTML
report can show it. Nothing lab-specific lives here — every value comes from the env.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from horizon_mcp.tools._confirm import CANCEL, PROCEED

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_ENV = ("HZ_BASE_URL", "HZ_USERNAME", "HZ_DOMAIN", "HZ_PASSWORD")
CALL_TIMEOUT = float(os.environ.get("HZ_LIVE_CALL_TIMEOUT", "120"))
# How long the destructive farm test waits for provisioning / teardown.
PROVISION_TIMEOUT = float(os.environ.get("HZ_LIVE_PROVISION_TIMEOUT", "1800"))

# What config._describe_changes says when a settings/policies PUT changes nothing.
NOOP_MARKER = "no fields differ from the current values"

_SECRET_KEY = re.compile(r"token|password|secret|ticket|credential", re.I)


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "y")


def missing_env() -> list[str]:
    return [k for k in REQUIRED_ENV if not os.environ.get(k)]


WRITES = _flag("HZ_LIVE_WRITES")
DESTRUCTIVE = _flag("HZ_LIVE_DESTRUCTIVE")

# ── Shared state collected across the session, for the report ────────────────
ROWS: list[dict] = []
PROMPTS: list[dict] = []
TOOLS: list[str] = []
# Per-tool verdicts from the end-to-end lifecycle test ({tool: {"status", "detail"}}), for the report.
COVERAGE: dict[str, dict] = {}
_SERVER_LOG: Path | None = None


def server_log_path() -> Path:
    """One stderr log for every server process spawned in this pytest session."""
    global _SERVER_LOG
    if _SERVER_LOG is None:
        explicit = os.environ.get("HZ_LIVE_SERVER_LOG")
        if explicit:
            _SERVER_LOG = Path(explicit)
            _SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, name = tempfile.mkstemp(prefix="horizon-mcp-live-", suffix=".log")
            os.close(fd)
            _SERVER_LOG = Path(name)
    return _SERVER_LOG


# ── Data helpers ─────────────────────────────────────────────────────────────

class Masked(str):
    """A str that never shows its value in a repr — so a password or token can't leak into
    a pytest traceback (which prints the arguments of every frame)."""

    def __repr__(self) -> str:
        return "'[REDACTED]'"


def mask_secrets(obj: Any) -> Any:
    """Wrap string values under secret-looking keys in Masked (values stay usable)."""
    if isinstance(obj, dict):
        return {k: Masked(v) if isinstance(v, str) and _SECRET_KEY.search(str(k)) else mask_secrets(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_secrets(v) for v in obj]
    return obj


def redact(obj: Any) -> Any:
    """Mask secret-looking keys, and the test password wherever it appears."""
    password = os.environ.get("HZ_PASSWORD") or None
    if isinstance(obj, dict):
        return {k: "[REDACTED]" if _SECRET_KEY.search(str(k)) else redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str) and password and password in obj:
        return obj.replace(password, "[REDACTED]")
    return obj


def items(data: Any) -> list:
    """List results as a list — accepts a bare list or a paginated {"items": [...]} dict."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    return []


def first(data: Any, pred=lambda x: True) -> dict | None:
    return next((x for x in items(data) if isinstance(x, dict) and pred(x)), None)


def by_name(data: Any, name: str) -> dict | None:
    return first(data, lambda x: x.get("name") == name)


def walk(data: Any):
    """Every dict in a nested structure (vCenter folder / resource-pool trees have children)."""
    if isinstance(data, list):
        for x in data:
            yield from walk(x)
    elif isinstance(data, dict):
        yield data
        for v in data.values():
            if isinstance(v, (list, dict)):
                yield from walk(v)


def pick(data: Any, env_var: str) -> dict | None:
    """The entry whose id/name/path matches env_var if it's set, else the first entry."""
    want = os.environ.get(env_var)
    if not want:
        return first(data)
    keys = ("id", "name", "display_name", "path", "username")
    return next((d for d in walk(items(data) or data) if any(d.get(k) == want for k in keys)), None)


def payload(result: Any) -> Any:
    if getattr(result, "data", None) is not None:
        return result.data
    sc = getattr(result, "structured_content", None)
    if isinstance(sc, dict) and set(sc) == {"result"}:
        return sc["result"]
    if sc is not None:
        return sc
    return "\n".join(getattr(c, "text", "") for c in (result.content or []))


def classify(data: Any) -> tuple[str, str]:
    if data in (None, [], {}, ""):
        return "EMPTY", "Call succeeded, no data returned"
    if isinstance(data, list) or (isinstance(data, dict) and isinstance(data.get("items"), list)):
        return "PASS", f"{len(items(data))} item(s)"
    if isinstance(data, dict):
        errs = [k for k, v in data.items() if isinstance(v, dict) and "error" in v]
        if errs:
            return "WARN", f"{len(data)} section(s); errors in: {', '.join(errs)}"
        return "PASS", f"{len(data)} field(s)"
    return "PASS", str(data)[:120]


def credentials() -> dict:
    return {
        "username": os.environ.get("HZ_USERNAME", ""),
        "password": Masked(os.environ.get("HZ_PASSWORD", "")),
        "domain": os.environ.get("HZ_DOMAIN", ""),
    }


def server_env() -> dict[str, str]:
    """Environment for the spawned server: none of our HZ_* (incl. the password) or stray
    HORIZON_*/MCP_* settings leak in; confirmation is forced to real elicitation."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HZ_", "HORIZON_", "MCP_"))}
    env.update(
        HORIZON_BASE_URL=os.environ["HZ_BASE_URL"],
        HORIZON_VERIFY_SSL=os.environ.get("HZ_VERIFY_SSL", "true"),
        HORIZON_CONFIRMATION="elicit",
        MCP_TRANSPORT="stdio",
    )
    return env


# ── Confirmation prompts ─────────────────────────────────────────────────────

class Approver:
    """MCP elicitation handler that stands in for the user, as narrowly as possible.

    Approves a prompt only if it names an ID the test registered with allow() (things the
    test itself created, or HZ_TEST_FARM's ID), or — for settings/policies round trips — if
    it starts with a registered prefix AND says nothing changes. Everything else is
    cancelled, so a bug can never get an unintended destructive action approved.
    """

    def __init__(self, prompts: list[dict] | None = None) -> None:
        self.prompts = PROMPTS if prompts is None else prompts
        self.ids: set[str] = set()
        self.noop_prefixes: list[str] = []
        self.restore_prefixes: list[str] = []
        self.seen: list[tuple[bool, str]] = []

    def allow(self, *ids: str) -> None:
        self.ids.update(i for i in ids if i)

    def allow_noop(self, prefix: str) -> None:
        self.noop_prefixes.append(prefix)

    def allow_restore(self, prefix: str) -> None:
        """Approve any change under `prefix` — only used to write a saved original back."""
        self.restore_prefixes.append(prefix)

    def _decide(self, message: str) -> bool:
        if any(i in message for i in self.ids):
            return True
        head = message.splitlines()[0] if message else ""
        if any(head.startswith(p) for p in self.restore_prefixes):
            return True
        return any(head.startswith(p) and NOOP_MARKER in head for p in self.noop_prefixes)

    async def __call__(self, message, response_type, params, context):
        ok = self._decide(message)
        self.seen.append((ok, message))
        self.prompts.append({"approved": ok, "message": redact(message)})
        print(f"  [confirm → {PROCEED if ok else CANCEL}] {redact(message.splitlines()[0])}")
        return {"value": PROCEED if ok else CANCEL}

    def unexpected(self) -> list[str]:
        return [m for ok, m in self.seen if not ok]

    def assert_all_expected(self) -> None:
        bad = self.unexpected()
        assert not bad, f"Unexpected confirmation prompt(s), cancelled: {redact(bad)}"

    def assert_prompted(self, fragment: str) -> None:
        assert any(ok and fragment in m for ok, m in self.seen), (
            f"Expected an approved confirmation prompt mentioning {fragment!r}; saw {redact(self.seen)}"
        )


# ── Calling tools ────────────────────────────────────────────────────────────

class LiveToolError(AssertionError):
    pass


class Session:
    def __init__(self, client: Client, group: str, approver: Approver, rows: list[dict] | None = None) -> None:
        self.client = client
        self.group = group
        self.approver = approver
        self.rows = ROWS if rows is None else rows

    def record(self, label: str, status: str, summary: str, *, args=None, body=None, ms: int = 0) -> None:
        self.rows.append(dict(group=self.group, tool=label, status=status, args=redact(args),
                              ms=ms, summary=redact(summary), body=redact(body)))
        print(f"  {status:5} {label:48} {ms or '':>6}")

    def mark_last(self, status: str, note: str | None = None) -> None:
        """Re-label the row the last call recorded — e.g. an expected rejection as NA."""
        row = self.rows[-1]
        row["status"] = status
        if note:
            row["summary"] = redact(f"{note} — {row['summary']}")
        print(f"  {'':5} └─ {status}: {redact(note or '')[:100]}")

    def skip(self, label: str, reason: str) -> None:
        self.record(label, "SKIP", reason)

    async def attempt(self, tool: str, args: dict | None = None, *, label: str | None = None,
                      timeout: float = CALL_TIMEOUT) -> tuple[bool, Any, str]:
        """Call a tool; never raises. Returns (ok, data, summary)."""
        __tracebackhide__ = True
        args = args or {}
        t0 = time.perf_counter()
        try:
            res = await self.client.call_tool(tool, args, raise_on_error=False, timeout=timeout)
            data = mask_secrets(payload(res))
            if res.is_error:
                ok, status, summary = False, "FAIL", str(data)[:500]
            else:
                ok = True
                status, summary = classify(data)
        except Exception as e:  # transport error / timeout
            data, ok, status, summary = None, False, "FAIL", f"{type(e).__name__}: {e}"[:500]
        ms = int((time.perf_counter() - t0) * 1000)
        self.record(label or tool, status, summary, args=args, body=data, ms=ms)
        return ok, data, summary

    async def call(self, tool: str, args: dict | None = None, **kw) -> Any:
        """Call a tool; raise LiveToolError if it fails."""
        __tracebackhide__ = True
        ok, data, summary = await self.attempt(tool, args, **kw)
        if not ok:
            raise LiveToolError(f"{kw.get('label') or tool} failed: {redact(summary)}")
        return data

    async def read_json_resource(self, uri: str) -> Any:
        t0 = time.perf_counter()
        try:
            contents = await self.client.read_resource(uri)
            text = "".join(getattr(c, "text", "") or "" for c in contents)
            data = json.loads(text) if text else None
        except Exception as e:
            self.record(f"resource {uri}", "FAIL", f"{type(e).__name__}: {e}"[:500],
                        ms=int((time.perf_counter() - t0) * 1000))
            raise LiveToolError(f"Reading {uri} failed: {redact(str(e))}") from e
        status, summary = classify(data)
        self.record(f"resource {uri}", status, summary, body=data, ms=int((time.perf_counter() - t0) * 1000))
        return data

    async def list_all(self, tool: str, **args) -> list:
        """A list tool's first page at max size, as a list (lab-sized environments)."""
        return items(await self.call(tool, {"size": 1000, **args}))


@asynccontextmanager
async def live_session(group: str, approver: Approver | None = None, *, login: bool = True
                       ) -> AsyncIterator[Session]:
    """Spawn the server over stdio, optionally log in, and log out again on exit."""
    __tracebackhide__ = True
    approver = approver or Approver()
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "horizon_mcp"],
        env=server_env(),
        cwd=str(REPO_ROOT),
        keep_alive=False,
        log_file=server_log_path(),
    )
    async with Client(transport, elicitation_handler=approver) as client:
        if not TOOLS:
            TOOLS.extend(t.name for t in await client.list_tools())
        s = Session(client, group, approver)
        logged_in = False
        if login:
            await s.call("horizon_login", credentials())
            logged_in = True
        try:
            yield s
        finally:
            if logged_in:  # the server holds the refresh token; logout needs no argument
                await s.attempt("horizon_logout")


async def poll(fn, *, timeout: float, interval: float = 10.0, what: str = "condition"):
    """Await fn() until it returns something truthy, or fail after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while True:
        result = await fn()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError(f"Timed out after {timeout:.0f}s waiting for {what}")
        await asyncio.sleep(interval)
