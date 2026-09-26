"""Audit log of destructive decisions and mutating Horizon API calls.

One JSON object per line on the "horizon_mcp.audit" logger. Output goes to stderr,
or to the file named by HORIZON_AUDIT_LOG — never stdout, which stdio transport
uses for the MCP protocol itself.

Callers pass only what's safe to keep: method, path, status, confirmation summary.
Request bodies, tokens, passwords and headers are never passed in, so they can't
end up in the log.
"""
import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone

from fastmcp.server.middleware import Middleware

logger = logging.getLogger("horizon_mcp.audit")
logger.setLevel(logging.INFO)
# Don't hand records to the root logger — its handlers could be writing to stdout.
logger.propagate = False

_current_tool: contextvars.ContextVar[str | None] = contextvars.ContextVar("horizon_audit_tool", default=None)
_target: str | None = None


class _StderrHandler(logging.Handler):
    """Write to whatever sys.stderr is at emit time (a StreamHandler would pin the
    stream object it was created with)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


def _configure() -> None:
    """Point the logger at stderr or HORIZON_AUDIT_LOG, re-pointing it if that changed."""
    global _target
    target = os.environ.get("HORIZON_AUDIT_LOG", "").strip() or "stderr"
    if target == _target:
        return
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    handler: logging.Handler
    if target == "stderr":
        handler = _StderrHandler()
    else:
        try:
            handler = logging.FileHandler(target, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"horizon-mcp: can't open HORIZON_AUDIT_LOG ({exc}); auditing to stderr\n")
            handler = _StderrHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    _target = target


def record(event: str, **fields) -> None:
    """Write one audit line. Only pass values that are safe to persist."""
    _configure()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "event": event,
        "tool": _current_tool.get(),
        **fields,
    }
    logger.info(json.dumps(entry, default=str))


class ToolNameMiddleware(Middleware):
    """Remember which tool is running so audit lines can name it."""

    async def on_call_tool(self, context, call_next):
        token = _current_tool.set(getattr(context.message, "name", None))
        try:
            return await call_next(context)
        finally:
            _current_tool.reset(token)
