"""Tests for inventory tools: machine_action, logoff_sessions, session actions."""
import pytest
from unittest.mock import patch, AsyncMock

from .conftest import MockFastMCP
from horizon_mcp.tools import inventory
from horizon_mcp.tools.inventory import _MACHINE_ACTIONS, _FORCE_APPLICABLE_ACTIONS


@pytest.fixture
def tools(mock_mcp: MockFastMCP):
    inventory.register(mock_mcp)
    return mock_mcp.tools


# ── machine_action constants ───────────────────────────────────────────────────

def test_machine_actions_have_expected_keys():
    assert set(_MACHINE_ACTIONS) == {
        "shutdown", "restart", "reset", "rebuild",
        "recover", "enter_maintenance", "exit_maintenance", "archive",
    }


def test_force_applicable_actions():
    assert _FORCE_APPLICABLE_ACTIONS == {"shutdown", "restart"}


def test_object_body_actions_are_only_shutdown_and_restart():
    object_body = {k for k, (_, style) in _MACHINE_ACTIONS.items() if style == "object"}
    assert object_body == _FORCE_APPLICABLE_ACTIONS


# ── machine_action: body structure ─────────────────────────────────────────────

async def test_machine_action_shutdown_sends_object_body(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        await tools["machine_action"](
            machine_ids=["m-1", "m-2"], action="shutdown", force=False,
        )

    assert isinstance(captured["body"], dict)
    assert captured["body"]["machineIds"] == ["m-1", "m-2"]
    assert captured["body"]["forceOperation"] is False


async def test_machine_action_shutdown_force_true(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        await tools["machine_action"](
            machine_ids=["m-1"], action="shutdown", force=True,
        )

    assert captured["body"]["forceOperation"] is True


async def test_machine_action_rebuild_sends_array_body(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        await tools["machine_action"](
            machine_ids=["m-1", "m-2"], action="rebuild",
        )

    assert isinstance(captured["body"], list)
    assert captured["body"] == ["m-1", "m-2"]


@pytest.mark.parametrize("action", [
    "reset", "rebuild", "recover", "enter_maintenance", "exit_maintenance", "archive",
])
async def test_machine_action_force_true_raises_for_non_applicable(tools, action):
    with pytest.raises(ValueError, match="force=True is only applicable"):
        await tools["machine_action"](
            machine_ids=["m-1"], action=action, force=True,
        )


async def test_machine_action_force_false_does_not_raise_for_non_applicable(tools):
    with patch("horizon_mcp.tools.inventory.api_post", return_value=None):
        result = await tools["machine_action"](
            machine_ids=["m-1"], action="rebuild", force=False,
        )
    assert result["action"] == "rebuild"


# ── logoff_sessions ────────────────────────────────────────────────────────────

async def test_logoff_sessions_sends_ids_as_body(tools):
    captured: dict = {}

    async def fake_post(path, body, params=None):
        captured["body"] = body
        captured["params"] = params
        return None

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        await tools["logoff_sessions"](session_ids=["s-1", "s-2"])

    assert captured["body"] == ["s-1", "s-2"]


async def test_logoff_sessions_forced_sent_as_query_param(tools):
    captured: dict = {}

    async def fake_post(path, body, params=None):
        captured["params"] = params
        return None

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        await tools["logoff_sessions"](session_ids=["s-1"], forced=True)

    assert captured["params"] == {"forced": "true"}


async def test_logoff_sessions_default_forced_is_false(tools):
    captured: dict = {}

    async def fake_post(path, body, params=None):
        captured["params"] = params
        return None

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        await tools["logoff_sessions"](session_ids=["s-1"])

    assert captured["params"] == {"forced": "false"}


# ── disconnect_sessions ────────────────────────────────────────────────────────

async def test_disconnect_sessions_sends_ids_as_body(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        await tools["disconnect_sessions"](session_ids=["s-a", "s-b"])

    assert captured["body"] == ["s-a", "s-b"]


# ── send_message_to_sessions ───────────────────────────────────────────────────

async def test_send_message_includes_all_fields(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        await tools["send_message_to_sessions"](
            session_ids=["s-1"],
            message="Maintenance in 10 minutes",
            message_type="WARNING",
        )

    assert captured["body"]["message"] == "Maintenance in 10 minutes"
    assert captured["body"]["message_type"] == "WARNING"
    assert captured["body"]["session_ids"] == ["s-1"]
