"""Tests for config tools: list_image_management, trigger_connection_server_backup."""
import pytest
from unittest.mock import patch

from .conftest import MockFastMCP
from horizon_mcp.tools import config


@pytest.fixture
def tools(mock_mcp: MockFastMCP):
    config.register(mock_mcp)
    return mock_mcp.tools


# ── list_image_management ──────────────────────────────────────────────────────

async def test_list_image_management_streams_needs_no_stream_id(tools):
    captured: dict = {}

    async def fake_api_get(path, params=None):
        captured["path"] = path
        captured["params"] = params
        return [{"id": "s1"}]

    with patch("horizon_mcp.tools.config.api_get", side_effect=fake_api_get):
        result = await tools["list_image_management"](resource="streams")

    assert captured == {"path": "/config/v1/im-streams", "params": None}
    assert result == [{"id": "s1"}]


@pytest.mark.parametrize("resource,expected_path", [
    ("versions", "/config/v1/im-versions"),
    ("tags", "/config/v1/im-tags"),
])
async def test_list_image_management_passes_stream_id(tools, resource, expected_path):
    captured: dict = {}

    async def fake_api_get(path, params=None):
        captured["path"] = path
        captured["params"] = params
        return [{"id": resource}]

    with patch("horizon_mcp.tools.config.api_get", side_effect=fake_api_get):
        result = await tools["list_image_management"](resource=resource, stream_id="s1")

    assert captured == {"path": expected_path, "params": {"im_stream_id": "s1"}}
    assert result == [{"id": resource}]


@pytest.mark.parametrize("resource", ["versions", "tags"])
async def test_list_image_management_requires_stream_id(tools, resource):
    with patch("horizon_mcp.tools.config.api_get") as mock_get:
        with pytest.raises(ValueError, match="stream_id is required"):
            await tools["list_image_management"](resource=resource)
    mock_get.assert_not_called()


async def test_list_image_management_returns_empty_on_none(tools):
    with patch("horizon_mcp.tools.config.api_get", return_value=None):
        result = await tools["list_image_management"](resource="streams")
    assert result == []


# ── trigger_connection_server_backup ──────────────────────────────────────────

async def test_trigger_backup_sends_empty_list_when_no_ids(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.config.api_post", side_effect=fake_post):
        result = await tools["trigger_connection_server_backup"]()

    assert captured["body"] == []
    assert result == {"success": True}


async def test_trigger_backup_sends_specified_ids(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.config.api_post", side_effect=fake_post):
        await tools["trigger_connection_server_backup"](server_ids=["cs-1", "cs-2"])

    assert captured["body"] == ["cs-1", "cs-2"]


async def test_trigger_backup_uses_correct_endpoint(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["path"] = path
        return None

    with patch("horizon_mcp.tools.config.api_post", side_effect=fake_post):
        await tools["trigger_connection_server_backup"]()

    assert captured["path"] == "/config/v1/connection-servers/action/backup"
