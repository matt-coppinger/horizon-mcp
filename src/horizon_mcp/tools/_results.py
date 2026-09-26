"""Shape Horizon write responses into the dict results the tools declare.

Horizon's bulk endpoints (machine/session/pool actions, entitlements, backups) return
a JSON array with one BulkItemResponseInfo per item — {id, status_code, errors,
error_messages, ...} — and many create/update/delete endpoints return no body at all
(201/204). Returning the raw list from a tool declared `-> dict` makes FastMCP reject
the result, so the model is told the call failed even though Horizon did the work.
"""
from typing import Any


def _item_failed(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    status = item.get("status_code")
    return bool(item.get("errors") or item.get("error_messages")) or (
        isinstance(status, int) and status >= 400
    )


def bulk_result(result: Any, **summary: Any) -> dict:
    """Summarise a bulk response: which items succeeded and which failed (with errors)."""
    if isinstance(result, dict):
        return {"success": True, **summary, **result}
    if not isinstance(result, list):
        return {"success": True, **summary}
    failed = [
        {k: item.get(k) for k in ("id", "key", "status_code", "errors", "error_messages") if item.get(k)}
        for item in result
        if _item_failed(item)
    ]
    return {
        "success": not failed,
        **summary,
        "succeeded": len(result) - len(failed),
        "failed": failed,
    }
