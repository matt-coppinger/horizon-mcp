"""End-to-end lifecycle test: every tool the server exposes, against a real Horizon lab.

Opt-in with HZ_LIVE_E2E=1 (plus the four standard HZ_* variables). Lab only, never production.
One command: it deletes leftovers from earlier runs (only items named HZ_E2E_PREFIX*,
default "mcp-e2e-"), creates a 1-machine instant-clone desktop pool, a 1-server
instant-clone RDS farm and an application pool on it, exercises every tool, deletes what
it created, and fails if any registered tool was neither called nor skipped with a reason.

See lifecycle.py for the flow and README "End-to-end lifecycle test" for the variables.
Plan / dry run, offline: uv run python -m tests.live.lifecycle --plan
"""
import pytest

from . import harness
from .harness import _flag, live_session
from .lifecycle import Config, format_coverage, run_e2e

pytestmark = pytest.mark.skipif(not _flag("HZ_LIVE_E2E"),
                                reason="The end-to-end lifecycle test is opt-in: set HZ_LIVE_E2E=1 (lab only)")


async def test_full_lifecycle(capsys):
    cfg = Config.from_env()
    problems = cfg.problems()
    if problems:
        pytest.fail("Can't run the end-to-end test:\n  " + "\n  ".join(problems), pytrace=False)

    def opener(group, approver):
        return live_session(group, approver, login=False)  # the flow logs in and out itself

    # A long, stateful run: show progress (and the "connect now" prompt) as it happens.
    with capsys.disabled():
        print(f"\nhorizon-mcp end-to-end run {cfg.tag}: creates {cfg.pool_name}, {cfg.farm_name}, {cfg.app_name}")
        result = await run_e2e(opener, cfg, rows=harness.ROWS)
        if result.logged_in:
            harness.COVERAGE.update(result.coverage)
            print("\nTool coverage:\n" + format_coverage(result))
        print("\n" + result.summary())
    if not result.ok:
        pytest.fail("End-to-end lifecycle failed:\n" + result.summary(), pytrace=False)
