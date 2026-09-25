"""Tests for human-in-the-loop confirmation (MCP elicitation) on destructive tools."""
import pytest
from unittest.mock import patch

from .conftest import MockFastMCP
from horizon_mcp.tools import _confirm, config, entitlements, helpdesk, inventory
from horizon_mcp.tools._confirm import CANCEL, PROCEED, ConfirmationRequired, require_confirmation


class _Result:
    def __init__(self, action, data=None):
        self.action = action
        self.data = data


class _Session:
    def __init__(self, supports):
        self.supports = supports

    def check_client_capability(self, caps):
        return self.supports and caps.elicitation is not None


class _Ctx:
    def __init__(self, supports=True, result=None):
        self.session = _Session(supports)
        self.result = result
        self.prompts: list = []

    async def elicit(self, message, response_type=None, **kwargs):
        self.prompts.append((message, response_type))
        return self.result


def _with_ctx(ctx):
    if ctx is None:
        return patch.object(_confirm, "get_context", side_effect=RuntimeError("No active context found."))
    return patch.object(_confirm, "get_context", return_value=ctx)


# ── require_confirmation ──────────────────────────────────────────────────────

async def test_user_proceeds(monkeypatch):
    ctx = _Ctx(result=_Result("accept", PROCEED))
    with _with_ctx(ctx):
        await require_confirmation("Delete pool X")
    message, choices = ctx.prompts[0]
    assert "Delete pool X" in message
    assert choices == [PROCEED, CANCEL]


@pytest.mark.parametrize("result", [_Result("accept", CANCEL), _Result("decline"), _Result("cancel")])
async def test_user_cancels_declines_or_dismisses(result):
    with _with_ctx(_Ctx(result=result)):
        with pytest.raises(ConfirmationRequired, match="Cancelled by the user"):
            await require_confirmation("Delete pool X")


async def test_confirm_flag_cannot_bypass_elicitation():
    # The model setting confirm=True must not skip the prompt when the client can ask the user.
    ctx = _Ctx(result=_Result("decline"))
    with _with_ctx(ctx):
        with pytest.raises(ConfirmationRequired):
            await require_confirmation("Delete pool X", confirm=True)
    assert len(ctx.prompts) == 1


@pytest.mark.parametrize("ctx", [None, _Ctx(supports=False)])
async def test_refuses_without_elicitation_by_default(monkeypatch, ctx):
    monkeypatch.delenv("HORIZON_CONFIRMATION", raising=False)
    with _with_ctx(ctx):
        with pytest.raises(ConfirmationRequired, match="doesn't support elicitation"):
            await require_confirmation("Delete pool X", confirm=True)


@pytest.mark.parametrize("ctx", [None, _Ctx(supports=False)])
async def test_flag_mode_accepts_confirm_true(monkeypatch, ctx):
    monkeypatch.setenv("HORIZON_CONFIRMATION", "flag")
    with _with_ctx(ctx):
        await require_confirmation("Delete pool X", confirm=True)
        with pytest.raises(ConfirmationRequired, match="confirm=True is required"):
            await require_confirmation("Delete pool X", confirm=False)


# ── which tool calls ask ──────────────────────────────────────────────────────

@pytest.fixture
def tools(mock_mcp: MockFastMCP):
    for module in (inventory, helpdesk, entitlements, config):
        module.register(mock_mcp)
    return mock_mcp.tools


async def _ok(*args, **kwargs):
    return None


@pytest.mark.parametrize("name,kwargs", [
    ("machine_action", {"machine_ids": ["m1"], "action": "restart"}),
    ("machine_action", {"machine_ids": ["m1"], "action": "rebuild"}),
    ("logoff_sessions", {"session_ids": ["s1"]}),
    ("disconnect_sessions", {"session_ids": ["s1"]}),
    ("reset_or_restart_sessions", {"session_ids": ["s1"], "action": "reset"}),
    ("desktop_pool_action", {"pool_ids": ["p1"], "action": "disable"}),
    ("desktop_pool_action", {"pool_ids": ["p1"], "action": "disable-provisioning"}),
    ("end_remote_application", {"session_id": "s1", "remote_application_id": "a1"}),
    ("set_pool_entitlements", {"pool_id": "p1", "pool_type": "desktop", "action": "remove", "ad_user_or_group_ids": ["u1"]}),
    ("set_pool_entitlements", {"pool_id": "p1", "pool_type": "desktop", "action": "replace", "ad_user_or_group_ids": ["u1"]}),
    ("update_global_policies", {"spec": {"allow_usb_access": True}}),
    ("update_settings", {"setting_type": "security", "spec": {"x": 1}}),
])
async def test_destructive_calls_ask_and_stop_when_declined(tools, confirmations, name, kwargs):
    confirmations.approve = False
    with patch("horizon_mcp.tools.inventory.api_post", side_effect=_ok) as inv_post, \
         patch("horizon_mcp.tools.helpdesk.api_post", side_effect=_ok) as hd_post, \
         patch("horizon_mcp.tools.entitlements.api_put", side_effect=_ok) as ent_put, \
         patch("horizon_mcp.tools.entitlements.api_delete", side_effect=_ok) as ent_del, \
         patch("horizon_mcp.tools.config.api_put", side_effect=_ok) as cfg_put:
        with pytest.raises(ConfirmationRequired):
            await tools[name](**kwargs)
    assert len(confirmations) == 1
    for m in (inv_post, hd_post, ent_put, ent_del, cfg_put):
        m.assert_not_called()


@pytest.mark.parametrize("name,kwargs", [
    ("machine_action", {"machine_ids": ["m1"], "action": "recover"}),
    ("machine_action", {"machine_ids": ["m1"], "action": "exit_maintenance"}),
    ("desktop_pool_action", {"pool_ids": ["p1"], "action": "enable"}),
    ("set_pool_entitlements", {"pool_id": "p1", "pool_type": "desktop", "action": "add", "ad_user_or_group_ids": ["u1"]}),
])
async def test_non_destructive_calls_do_not_ask(tools, confirmations, name, kwargs):
    with patch("horizon_mcp.tools.inventory.api_post", side_effect=_ok), \
         patch("horizon_mcp.tools.entitlements.api_post", side_effect=_ok):
        await tools[name](**kwargs)
    assert confirmations == []


async def test_rdsh_farm_enable_does_not_ask_but_disable_does(tools, confirmations):
    farm = {"id": "f1", "enabled": True, "display_name": "f"}
    with patch("horizon_mcp.tools.inventory.api_get", return_value=farm), \
         patch("horizon_mcp.tools.inventory.api_put", side_effect=_ok):
        await tools["rdsh_farm_action"](farm_ids=["f1"], action="enable")
        assert confirmations == []
        await tools["rdsh_farm_action"](farm_ids=["f1"], action="disable")
    assert len(confirmations) == 1 and "Disable 1 RDS farm" in confirmations[0]


async def test_forced_machine_action_is_called_out(tools, confirmations):
    with patch("horizon_mcp.tools.inventory.api_post", side_effect=_ok):
        await tools["machine_action"](machine_ids=["m1", "m2"], action="shutdown", force=True)
    assert "Shutdown 2 machine(s) (forced" in confirmations[0]


# ── prompt helpers ────────────────────────────────────────────────────────────

async def test_label_uses_name_and_falls_back_to_id(monkeypatch):
    monkeypatch.undo()  # use the real helpers, not the conftest stand-ins
    with patch("horizon_mcp.tools.inventory.api_get", return_value={"display_name": "Sales"}):
        assert await inventory._label("/x", "p1") == "Sales (p1)"
    with patch("horizon_mcp.tools.inventory.api_get", side_effect=ValueError("404")):
        assert await inventory._label("/x", "p1") == "p1"


async def test_describe_changes_lists_only_changed_fields(monkeypatch):
    monkeypatch.undo()
    current = {"allow_usb_access": False, "allow_multimedia_redirection": True}
    with patch("horizon_mcp.tools.config.api_get", return_value=current):
        text = await config._describe_changes("/x", {"allow_usb_access": True, "allow_multimedia_redirection": True})
    assert text == "allow_usb_access: False → True"


# ── end to end over the MCP protocol ──────────────────────────────────────────

async def _call_delete(elicitation_handler):
    from fastmcp import Client

    from horizon_mcp.server import mcp

    async with Client(mcp, elicitation_handler=elicitation_handler) as client:
        return await client.call_tool(
            "delete_desktop_pool", {"pool_id": "pool-abc", "confirm": True}, raise_on_error=False
        )


@pytest.mark.parametrize("answer,deleted", [(PROCEED, True), (CANCEL, False)])
async def test_real_client_prompt_controls_the_delete(monkeypatch, answer, deleted):
    monkeypatch.undo()  # real require_confirmation, not the conftest stand-in
    prompts = []

    async def handler(message, response_type, params, context):
        prompts.append(message)
        return {"value": answer}

    with patch("horizon_mcp.tools.inventory.api_get", return_value={"name": "Sales"}), \
         patch("horizon_mcp.tools.inventory.api_delete", return_value=None) as mock_delete:
        result = await _call_delete(handler)

    assert "Delete desktop pool Sales (pool-abc)" in prompts[0]
    assert mock_delete.called is deleted
    assert result.is_error is (not deleted)


async def test_real_client_without_elicitation_is_refused(monkeypatch):
    monkeypatch.undo()
    monkeypatch.delenv("HORIZON_CONFIRMATION", raising=False)
    with patch("horizon_mcp.tools.inventory.api_get", return_value={"name": "Sales"}), \
         patch("horizon_mcp.tools.inventory.api_delete", return_value=None) as mock_delete:
        result = await _call_delete(None)
    assert result.is_error
    assert "doesn't support elicitation" in str(result.content[0].text)
    mock_delete.assert_not_called()
