"""Live integration suite: marks everything under tests/live as `live` and skips it unless
HZ_BASE_URL / HZ_USERNAME / HZ_DOMAIN / HZ_PASSWORD are set, so plain `pytest` stays offline."""
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from . import harness

LIVE_DIR = Path(__file__).resolve().parent
_STARTED = (datetime.now().strftime("%Y-%m-%d %H:%M"), time.perf_counter())


def pytest_collection_modifyitems(config, items):
    missing = harness.missing_env()
    skip = pytest.mark.skip(reason=f"Live tests need {', '.join(missing)} — see README 'Live integration tests'")
    for item in items:
        if LIVE_DIR in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.live)
            if missing:
                item.add_marker(skip, append=False)


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("HZ_LIVE_REPORT")
    if not out or not harness.ROWS:
        return
    from .report import render

    stats = session.config.pluginmanager.get_plugin("terminalreporter")
    outcomes = {k: len(stats.stats.get(k, [])) for k in ("passed", "failed", "skipped", "error")} if stats else {}
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(harness.ROWS, harness.TOOLS, harness.PROMPTS, started=_STARTED[0],
                           duration=time.perf_counter() - _STARTED[1], outcomes=outcomes,
                           coverage=harness.COVERAGE or None), encoding="utf-8")


def pytest_terminal_summary(terminalreporter):
    if not harness.ROWS:
        return
    terminalreporter.write_line(f"Horizon MCP server log: {harness.server_log_path()}")
    if os.environ.get("HZ_LIVE_REPORT"):
        terminalreporter.write_line(f"Horizon MCP live report: {os.environ['HZ_LIVE_REPORT']}")
