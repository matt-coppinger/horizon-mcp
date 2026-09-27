"""Offline dry run of the live end-to-end lifecycle test (tests/live/test_lifecycle.py).

Runs the real flow against the real server in-process, with every Horizon request
answered by tests/live/fake_horizon.py. Catches a new tool the lifecycle doesn't cover,
cleanup touching anything outside the prefix, and unexpected confirmation prompts —
without a lab.
"""
import asyncio
import contextlib
import io

import pytest
from fastmcp import Client

from horizon_mcp.server import mcp

from .live.fake_horizon import FAKE_TICKET, run_offline
from .live.lifecycle import DEFAULT_PREFIX, SESSION_TOOLS, Config, main


@pytest.fixture
def confirmations():
    """Override the autouse stand-in from conftest.py: this test drives real elicitation."""
    return None


def _run(**kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return run_offline(**kw)


def _registered() -> set[str]:
    async def go():
        async with Client(mcp) as c:
            return {t.name for t in await c.list_tools()}
    return asyncio.run(go())


@pytest.fixture(scope="module")
def with_sessions():
    return _run(wait_for_session=True)


def test_every_registered_tool_is_accounted_for(with_sessions):
    result, _ = with_sessions
    assert set(result.coverage) == _registered()
    assert result.ok, result.summary()
    statuses = {t: v["status"] for t, v in result.coverage.items()}
    assert {t for t, s in statuses.items() if s != "PASS"} == {"list_audit_events", "update_settings"}, statuses


def test_cleanup_only_touches_prefixed_items(with_sessions):
    _, fake = with_sessions
    assert fake.protected_names <= fake.names()
    assert fake.deleted and all(n.startswith(DEFAULT_PREFIX) for n in fake.deleted)
    assert not any(n.startswith(DEFAULT_PREFIX) for n in fake.names())
    assert {f"{DEFAULT_PREFIX}app-old1", f"{DEFAULT_PREFIX}vdi-old1", f"{DEFAULT_PREFIX}farm-old1"} <= set(fake.deleted)


def test_no_unexpected_prompts_and_secrets_redacted(with_sessions):
    result, _ = with_sessions
    assert not result.unexpected_prompts
    assert not result.leftovers
    assert FAKE_TICKET not in repr(result.rows)


def test_without_sessions_the_session_tools_are_skipped_with_a_reason():
    result, _ = _run(wait_for_session=False)
    assert result.ok, result.summary()
    # get_session / diagnose_session still run in the read-only sweep, on any session the pod has.
    for t in set(SESSION_TOOLS) - {"get_session", "diagnose_session"}:
        assert result.coverage[t]["status"] == "SKIP" and "HZ_E2E_WAIT_FOR_SESSION" in result.coverage[t]["detail"]


@pytest.mark.parametrize("prefix", ["", "mcp", "mcp-", "a b c d", "*mcp-e2e", "mcp/e2e-"])
def test_unsafe_prefix_is_refused(prefix):
    assert any("HZ_E2E_PREFIX" in p for p in Config(prefix=prefix).problems())


def test_missing_lab_settings_are_reported(monkeypatch):
    for var in ("HZ_POOL_BASE_VM", "HZ_POOL_SNAPSHOT", "HZ_FARM_BASE_VM", "HZ_FARM_SNAPSHOT", "HZ_BASE_VM",
                "HZ_SNAPSHOT", "HZ_TEST_GROUP", "HZ_TEST_USER", "HZ_E2E_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    problems = "\n".join(Config.from_env().problems())
    for var in ("HZ_POOL_BASE_VM", "HZ_POOL_SNAPSHOT", "HZ_BASE_VM", "HZ_SNAPSHOT", "HZ_TEST_GROUP", "HZ_TEST_USER"):
        assert var in problems
    assert "HZ_E2E_PREFIX" not in problems  # the default prefix is fine


def test_farm_falls_back_to_the_destructive_tests_variables(monkeypatch):
    monkeypatch.delenv("HZ_FARM_BASE_VM", raising=False)
    monkeypatch.delenv("HZ_FARM_SNAPSHOT", raising=False)
    cfg = Config.from_env()
    assert (cfg.farm_base_vm_env, cfg.farm_snapshot_env) == ("HZ_BASE_VM", "HZ_SNAPSHOT")
    monkeypatch.setenv("HZ_FARM_BASE_VM", "x")
    assert Config.from_env().farm_base_vm_env == "HZ_FARM_BASE_VM"


def test_plan_command(capsys):
    assert main(["--plan", "--no-session"]) == 0
    out = capsys.readouterr().out
    assert "12 Machine power actions" in out and "Coverage of the registered tools" in out
