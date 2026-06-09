"""Tests for inventory tools: machine_action, logoff_sessions, session actions,
create/update/delete for desktop pools, RDS farms, and application pools."""
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


@pytest.mark.parametrize("action", ["rebuild", "reset", "archive"])
async def test_machine_action_raises_when_bulk_destructive_exceeds_limit(tools):
    many_ids = [f"m-{i}" for i in range(21)]
    with pytest.raises(ValueError, match="Refusing to"):
        await tools["machine_action"](machine_ids=many_ids, action=action)


@pytest.mark.parametrize("action", ["rebuild", "reset", "archive"])
async def test_machine_action_allows_bulk_destructive_at_limit(tools):
    ids_at_limit = [f"m-{i}" for i in range(20)]
    with patch("horizon_mcp.tools.inventory.api_post", return_value=None):
        result = await tools["machine_action"](machine_ids=ids_at_limit, action=action)
    assert result["action"] == action


@pytest.mark.parametrize("action", ["shutdown", "restart", "enter_maintenance", "exit_maintenance"])
async def test_machine_action_no_bulk_limit_for_non_destructive(tools):
    many_ids = [f"m-{i}" for i in range(50)]
    with patch("horizon_mcp.tools.inventory.api_post", return_value=None):
        result = await tools["machine_action"](machine_ids=many_ids, action=action)
    assert result is not None


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


# ── create_desktop_pool ────────────────────────────────────────────────────────

async def test_create_desktop_pool_posts_spec_verbatim(tools):
    captured: dict = {}
    spec = {"name": "TestPool", "type": "AUTOMATED", "source": "INSTANT_CLONE", "user_assignment": "FLOATING"}

    async def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return {"id": "pool-new"}

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        result = await tools["create_desktop_pool"](spec=spec)

    assert captured["path"] == "/inventory/v1/desktop-pools"
    assert captured["body"] == spec
    assert result == {"id": "pool-new"}


async def test_create_desktop_pool_returns_api_response(tools):
    spec = {"name": "TestPool", "type": "MANUAL", "source": "VIRTUAL_CENTER", "user_assignment": "DEDICATED"}

    with patch("horizon_mcp.tools.inventory.api_post", return_value={"id": "pool-123"}):
        result = await tools["create_desktop_pool"](spec=spec)

    assert result == {"id": "pool-123"}


async def test_create_desktop_pool_raises_on_none_response(tools):
    spec = {"name": "TestPool", "type": "AUTOMATED", "source": "INSTANT_CLONE", "user_assignment": "FLOATING"}

    with patch("horizon_mcp.tools.inventory.api_post", return_value=None):
        with pytest.raises(ValueError, match="no response body"):
            await tools["create_desktop_pool"](spec=spec)


async def test_create_desktop_pool_raises_when_max_machine_count_exceeds_ceiling(tools):
    spec = {
        "name": "HugePool", "type": "AUTOMATED", "source": "INSTANT_CLONE",
        "user_assignment": "FLOATING",
        "provisioning_settings": {"max_machine_count": 9999},
    }
    with pytest.raises(ValueError, match="exceeds the safety ceiling"):
        await tools["create_desktop_pool"](spec=spec)


async def test_create_desktop_pool_allows_max_machine_count_at_ceiling(tools):
    spec = {
        "name": "BigPool", "type": "AUTOMATED", "source": "INSTANT_CLONE",
        "user_assignment": "FLOATING",
        "provisioning_settings": {"max_machine_count": 500},
    }
    with patch("horizon_mcp.tools.inventory.api_post", return_value={"id": "pool-ok"}):
        result = await tools["create_desktop_pool"](spec=spec)
    assert result == {"id": "pool-ok"}


# ── update_desktop_pool ────────────────────────────────────────────────────────

async def test_update_desktop_pool_puts_to_correct_path(tools):
    captured: dict = {}
    spec = {"display_name": "Updated Pool", "settings": {"enabled": False}}

    async def fake_put(path, body):
        captured["path"] = path
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.inventory.api_put", side_effect=fake_put):
        result = await tools["update_desktop_pool"](pool_id="pool-abc", spec=spec)

    assert captured["path"] == "/inventory/v1/desktop-pools/pool-abc"
    assert captured["body"] == spec
    assert result == {"success": True, "pool_id": "pool-abc"}


# ── delete_desktop_pool ────────────────────────────────────────────────────────

async def test_delete_desktop_pool_requires_confirm(tools):
    with pytest.raises(ValueError, match="confirm=True is required"):
        await tools["delete_desktop_pool"](pool_id="pool-abc")


async def test_delete_desktop_pool_confirm_false_raises(tools):
    with pytest.raises(ValueError, match="confirm=True is required"):
        await tools["delete_desktop_pool"](pool_id="pool-abc", confirm=False)


async def test_delete_desktop_pool_confirm_true_deletes_correct_path(tools):
    captured: dict = {}

    async def fake_delete(path):
        captured["path"] = path
        return None

    with patch("horizon_mcp.tools.inventory.api_delete", side_effect=fake_delete):
        result = await tools["delete_desktop_pool"](pool_id="pool-abc", confirm=True)

    assert captured["path"] == "/inventory/v1/desktop-pools/pool-abc"
    assert result == {"success": True, "pool_id": "pool-abc"}


# ── create_rdsh_farm ───────────────────────────────────────────────────────────

async def test_create_rdsh_farm_posts_spec_verbatim(tools):
    captured: dict = {}
    spec = {"name": "TestFarm", "type": "AUTOMATED", "source": "INSTANT_CLONE"}

    async def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return {"id": "farm-new"}

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        result = await tools["create_rdsh_farm"](spec=spec)

    assert captured["path"] == "/inventory/v1/farms"
    assert captured["body"] == spec
    assert result == {"id": "farm-new"}


async def test_create_rdsh_farm_returns_api_response(tools):
    spec = {"name": "TestFarm", "type": "MANUAL"}

    with patch("horizon_mcp.tools.inventory.api_post", return_value={"id": "farm-456"}):
        result = await tools["create_rdsh_farm"](spec=spec)

    assert result == {"id": "farm-456"}


async def test_create_rdsh_farm_raises_on_none_response(tools):
    spec = {"name": "TestFarm", "type": "AUTOMATED", "source": "INSTANT_CLONE"}

    with patch("horizon_mcp.tools.inventory.api_post", return_value=None):
        with pytest.raises(ValueError, match="no response body"):
            await tools["create_rdsh_farm"](spec=spec)


async def test_create_rdsh_farm_raises_when_max_machine_count_exceeds_ceiling(tools):
    spec = {
        "name": "HugeFarm", "type": "AUTOMATED", "source": "INSTANT_CLONE",
        "provisioning_settings": {"max_machine_count": 9999},
    }
    with pytest.raises(ValueError, match="exceeds the safety ceiling"):
        await tools["create_rdsh_farm"](spec=spec)


# ── update_rdsh_farm ───────────────────────────────────────────────────────────

async def test_update_rdsh_farm_puts_to_correct_path(tools):
    captured: dict = {}
    spec = {"display_name": "Updated Farm"}

    async def fake_put(path, body):
        captured["path"] = path
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.inventory.api_put", side_effect=fake_put):
        result = await tools["update_rdsh_farm"](farm_id="farm-xyz", spec=spec)

    assert captured["path"] == "/inventory/v1/farms/farm-xyz"
    assert captured["body"] == spec
    assert result == {"success": True, "farm_id": "farm-xyz"}


# ── delete_rdsh_farm ───────────────────────────────────────────────────────────

async def test_delete_rdsh_farm_requires_confirm(tools):
    with pytest.raises(ValueError, match="confirm=True is required"):
        await tools["delete_rdsh_farm"](farm_id="farm-xyz")


async def test_delete_rdsh_farm_confirm_false_raises(tools):
    with pytest.raises(ValueError, match="confirm=True is required"):
        await tools["delete_rdsh_farm"](farm_id="farm-xyz", confirm=False)


async def test_delete_rdsh_farm_confirm_true_deletes_correct_path(tools):
    captured: dict = {}

    async def fake_delete(path):
        captured["path"] = path
        return None

    with patch("horizon_mcp.tools.inventory.api_delete", side_effect=fake_delete):
        result = await tools["delete_rdsh_farm"](farm_id="farm-xyz", confirm=True)

    assert captured["path"] == "/inventory/v1/farms/farm-xyz"
    assert result == {"success": True, "farm_id": "farm-xyz"}


# ── create_application_pool ────────────────────────────────────────────────────

async def test_create_application_pool_required_fields_only(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        result = await tools["create_application_pool"](
            name="MyApp",
            farm_id="farm-123",
            executable_path=r"C:\apps\MyApp.lnk",
        )

    assert captured["path"] == "/inventory/v1/application-pools"
    body = captured["body"]
    assert body["name"] == "MyApp"
    assert body["farm_id"] == "farm-123"
    assert body["executable_path"] == r"C:\apps\MyApp.lnk"
    assert body["enable_pre_launch"] is False
    assert body["enable_client_restrictions"] is False
    assert body["multi_session_mode"] == "DISABLED"
    assert "display_name" not in body
    assert "publisher" not in body
    assert "version" not in body
    assert result == {"success": True}


async def test_create_application_pool_optional_fields_included_when_set(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.inventory.api_post", side_effect=fake_post):
        await tools["create_application_pool"](
            name="Brave",
            farm_id="farm-123",
            executable_path=r"C:\apps\Brave.lnk",
            display_name="Brave Browser",
            publisher="Brave Software",
            version="149.0",
            enable_pre_launch=True,
            multi_session_mode="ENABLED_DEFAULT_OFF",
        )

    body = captured["body"]
    assert body["display_name"] == "Brave Browser"
    assert body["publisher"] == "Brave Software"
    assert body["version"] == "149.0"
    assert body["enable_pre_launch"] is True
    assert body["multi_session_mode"] == "ENABLED_DEFAULT_OFF"


async def test_create_application_pool_returns_api_response_when_present(tools):
    with patch("horizon_mcp.tools.inventory.api_post", return_value={"id": "app-789"}):
        result = await tools["create_application_pool"](
            name="MyApp", farm_id="farm-123", executable_path=r"C:\apps\MyApp.lnk",
        )

    assert result == {"id": "app-789"}


# ── update_application_pool ────────────────────────────────────────────────────

async def test_update_application_pool_puts_to_correct_path(tools):
    captured: dict = {}
    spec = {"display_name": "My App Updated", "version": "2.0"}

    async def fake_put(path, body):
        captured["path"] = path
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.inventory.api_put", side_effect=fake_put):
        result = await tools["update_application_pool"](pool_id="app-abc", spec=spec)

    assert captured["path"] == "/inventory/v1/application-pools/app-abc"
    assert captured["body"] == spec
    assert result == {"success": True, "pool_id": "app-abc"}


# ── delete_application_pool ────────────────────────────────────────────────────

async def test_delete_application_pool_deletes_correct_path(tools):
    captured: dict = {}

    async def fake_delete(path):
        captured["path"] = path
        return None

    with patch("horizon_mcp.tools.inventory.api_delete", side_effect=fake_delete):
        result = await tools["delete_application_pool"](pool_id="app-abc")

    assert captured["path"] == "/inventory/v1/application-pools/app-abc"
    assert result == {"success": True, "pool_id": "app-abc"}
