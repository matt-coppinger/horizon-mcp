"""Tests for shaping Horizon write responses into the dicts the tools declare.

Horizon's bulk endpoints return a JSON array of BulkItemResponseInfo; returning that
raw from a `-> dict` tool makes FastMCP reject the result, so the model is told the
call failed even though Horizon did the work. The protocol tests below go through a
real FastMCP client, which is where that rejection happens.
"""
import pytest
from unittest.mock import patch

from horizon_mcp.tools._results import bulk_result


# ── bulk_result ───────────────────────────────────────────────────────────────

def test_all_items_succeeded():
    result = bulk_result([{"id": "m1", "status_code": 200}, {"id": "m2", "status_code": 204}], action="restart")
    assert result == {"success": True, "action": "restart", "succeeded": 2, "failed": []}


def test_partial_failure_is_reported():
    items = [
        {"id": "m1", "status_code": 200},
        {"id": "m2", "status_code": 400, "error_messages": ["Machine is not in a valid state"]},
        {"id": "m3", "errors": [{"error_key": "x", "error_message": "boom"}]},
    ]
    result = bulk_result(items)
    assert result["success"] is False
    assert result["succeeded"] == 1
    assert [f["id"] for f in result["failed"]] == ["m2", "m3"]
    assert result["failed"][0] == {"id": "m2", "status_code": 400, "error_messages": ["Machine is not in a valid state"]}


@pytest.mark.parametrize("raw", [None, [], {"id": "x"}])
def test_empty_or_non_list_bodies(raw):
    result = bulk_result(raw, session_count=1)
    assert result["success"] is True and result["session_count"] == 1


# ── through the MCP protocol ──────────────────────────────────────────────────

BULK_TOOLS = [
    ("machine_action", {"machine_ids": ["m1"], "action": "restart"}, "inventory"),
    ("machine_action", {"machine_ids": ["m1"], "action": "recover"}, "inventory"),
    ("desktop_pool_action", {"pool_ids": ["p1"], "action": "enable"}, "inventory"),
    ("assign_machine_users", {"machine_id": "m1", "user_ids": ["u1"], "action": "assign"}, "inventory"),
    ("disconnect_sessions", {"session_ids": ["s1"]}, "inventory"),
    ("logoff_sessions", {"session_ids": ["s1"]}, "inventory"),
    ("reset_or_restart_sessions", {"session_ids": ["s1"], "action": "restart"}, "inventory"),
    ("send_message_to_sessions", {"session_ids": ["s1"], "message": "hi"}, "inventory"),
    ("set_pool_entitlements", {"pool_id": "p1", "pool_type": "desktop", "action": "add", "ad_user_or_group_ids": ["u1"]}, "entitlements"),
    ("set_pool_entitlements", {"pool_id": "p1", "pool_type": "desktop", "action": "remove", "ad_user_or_group_ids": ["u1"]}, "entitlements"),
    ("trigger_connection_server_backup", {}, "config"),
]


def _returns(value):
    async def fake(*args, **kwargs):
        return value
    return fake


async def _call(name, args):
    from fastmcp import Client

    from horizon_mcp.server import mcp

    async def approve(message, response_type, params, context):
        return {"value": "Proceed"}

    async with Client(mcp, elicitation_handler=approve) as client:
        return await client.call_tool(name, args, raise_on_error=False)


@pytest.mark.parametrize("name,args,module", BULK_TOOLS, ids=lambda v: v if isinstance(v, str) else None)
async def test_bulk_list_response_is_not_reported_as_an_error(monkeypatch, name, args, module):
    monkeypatch.undo()  # real confirmation flow, answered by the client above
    import importlib

    mod = importlib.import_module(f"horizon_mcp.tools.{module}")
    horizon_says = [{"id": "x1", "status_code": 200}]
    for fn in ("api_post", "api_put", "api_delete"):
        if hasattr(mod, fn):
            monkeypatch.setattr(mod, fn, _returns(horizon_says))
    result = await _call(name, args)
    assert not result.is_error, result.content[0].text if result.content else result
    assert result.data["success"] is True
    assert result.data["succeeded"] == 1


async def test_bulk_partial_failure_reaches_the_model(monkeypatch):
    monkeypatch.undo()
    horizon_says = [{"id": "m1", "status_code": 200}, {"id": "m2", "status_code": 409, "error_messages": ["busy"]}]
    with patch("horizon_mcp.tools.inventory.api_post", return_value=horizon_says):
        result = await _call("machine_action", {"machine_ids": ["m1", "m2"], "action": "restart"})
    assert not result.is_error
    assert result.data["success"] is False
    assert result.data["failed"] == [{"id": "m2", "status_code": 409, "error_messages": ["busy"]}]


@pytest.mark.parametrize("name,args,lookup", [
    ("create_desktop_pool", {"spec": {"name": "P"}}, "/inventory/v13/desktop-pools"),
    ("create_rdsh_farm", {"spec": {"name": "P"}}, "/inventory/v10/farms"),
    ("create_application_pool", {"name": "P", "farm_id": "f1", "executable_path": "C:\\a.exe"}, "/inventory/v1/application-pools"),
])
async def test_create_with_empty_201_succeeds_over_protocol(monkeypatch, name, args, lookup):
    monkeypatch.undo()
    with patch("horizon_mcp.tools.inventory.api_post", return_value=None), \
         patch("horizon_mcp.tools.inventory.api_get", return_value=[{"id": "new-1", "name": "P"}]) as get:
        result = await _call(name, args)
    assert not result.is_error, result.content[0].text if result.content else result
    assert result.data == {"success": True, "id": "new-1", "name": "P"}
    assert get.call_args.args[0] == lookup
