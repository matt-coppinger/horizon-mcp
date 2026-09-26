"""Read-only sweep against a live Horizon server — changes nothing.

The whole sweep runs once (one server process, one login) in a session fixture; each
check then reports as its own test: PASS, FAIL with the tool's error, or SKIP when the
lab has nothing to feed the call (e.g. no active sessions for get_session).
"""
import asyncio
import warnings

import pytest

from .harness import ROWS, Approver, Session, live_session
from .sweep import planned_checks, run_sweep

CHECKS = planned_checks()


class _LiveRunner:
    def __init__(self, s: Session) -> None:
        self.s = s

    async def call(self, tool, args=None, label=None):
        ok, data, _ = await self.s.attempt(tool, args, label=label)
        return data if ok else None

    def skip(self, label, reason):
        self.s.skip(label, reason)

    def section(self, name):
        self.s.group = name


@pytest.fixture(scope="session")
def sweep():
    approver = Approver()  # nothing is allowed: a read-only tool must never prompt

    async def go():
        async with live_session("Auth", approver, login=False) as s:
            await run_sweep(_LiveRunner(s))

    start = len(ROWS)
    error = None
    try:
        asyncio.run(go())
    except Exception as e:  # spawn/connection failure — reported by every check
        error = f"{type(e).__name__}: {e}"
    rows = {r["tool"]: r for r in ROWS[start:]}
    return rows, error, approver


@pytest.mark.parametrize("check", CHECKS)
def test_read_only(check, sweep):
    rows, error, _ = sweep
    row = rows.get(check)
    if row is None:
        pytest.fail(f"Check never ran: {error or 'the sweep stopped before reaching it'}")
    if row["status"] == "SKIP":
        pytest.skip(row["summary"])
    assert row["status"] != "FAIL", row["summary"]
    if row["status"] == "WARN":
        warnings.warn(f"{check}: {row['summary']}", stacklevel=1)


def test_sweep_matches_plan(sweep):
    rows, error, _ = sweep
    assert error is None, error
    unplanned = sorted(set(rows) - set(CHECKS))
    assert not unplanned, f"Sweep produced checks the plan doesn't know about: {unplanned}"


def test_read_only_tools_never_prompt(sweep):
    _, _, approver = sweep
    assert not approver.seen, f"A read-only tool asked for confirmation: {approver.seen}"
