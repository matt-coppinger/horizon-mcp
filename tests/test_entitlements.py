"""Tests for consolidated entitlement tools."""
import pytest
from unittest.mock import patch

from .conftest import MockFastMCP
from horizon_mcp.tools import entitlements


@pytest.fixture
def tools(mock_mcp: MockFastMCP):
    entitlements.register(mock_mcp)
    return mock_mcp.tools


# ── list_pool_entitlements ─────────────────────────────────────────────────────

@pytest.mark.parametrize("pool_type", ["desktop", "application"])
async def test_list_pool_entitlements_calls_correct_endpoint(tools, pool_type):
    expected_path = f"/entitlements/v1/{pool_type}-pools"

    async def fake_api_get(path, params=None):
        assert path == expected_path
        return [{"id": "pool-1"}]

    with patch("horizon_mcp.tools.entitlements.api_get", side_effect=fake_api_get):
        result = await tools["list_pool_entitlements"](pool_type=pool_type)

    assert result == [{"id": "pool-1"}]


async def test_list_pool_entitlements_returns_empty_list_on_none(tools):
    with patch("horizon_mcp.tools.entitlements.api_get", return_value=None):
        result = await tools["list_pool_entitlements"](pool_type="desktop")
    assert result == []


# ── get_pool_entitlement ───────────────────────────────────────────────────────

@pytest.mark.parametrize("pool_type", ["desktop", "application"])
async def test_get_pool_entitlement_calls_correct_endpoint(tools, pool_type):
    expected_path = f"/entitlements/v1/{pool_type}-pools/pool-abc"

    async def fake_api_get(path, params=None):
        assert path == expected_path
        return {"id": "pool-abc", "ad_user_or_group_ids": ["user-1"]}

    with patch("horizon_mcp.tools.entitlements.api_get", side_effect=fake_api_get):
        result = await tools["get_pool_entitlement"](pool_id="pool-abc", pool_type=pool_type)

    assert result["id"] == "pool-abc"


# ── set_pool_entitlements ──────────────────────────────────────────────────────

async def test_set_pool_entitlements_add_uses_post(tools):
    with patch("horizon_mcp.tools.entitlements.api_post", return_value=None) as mock_post, \
         patch("horizon_mcp.tools.entitlements.api_put") as mock_put, \
         patch("horizon_mcp.tools.entitlements.api_delete") as mock_delete:
        result = await tools["set_pool_entitlements"](
            pool_id="pool-1", pool_type="desktop", action="add",
            ad_user_or_group_ids=["user-a"],
        )
    mock_post.assert_called_once()
    mock_put.assert_not_called()
    mock_delete.assert_not_called()
    assert result["action"] == "add"


async def test_set_pool_entitlements_replace_uses_put(tools):
    with patch("horizon_mcp.tools.entitlements.api_post") as mock_post, \
         patch("horizon_mcp.tools.entitlements.api_put", return_value=None) as mock_put, \
         patch("horizon_mcp.tools.entitlements.api_delete") as mock_delete:
        result = await tools["set_pool_entitlements"](
            pool_id="pool-1", pool_type="application", action="replace",
            ad_user_or_group_ids=["group-b"],
        )
    mock_put.assert_called_once()
    mock_post.assert_not_called()
    mock_delete.assert_not_called()
    assert result["action"] == "replace"


async def test_set_pool_entitlements_remove_uses_delete(tools):
    with patch("horizon_mcp.tools.entitlements.api_post") as mock_post, \
         patch("horizon_mcp.tools.entitlements.api_put") as mock_put, \
         patch("horizon_mcp.tools.entitlements.api_delete", return_value=None) as mock_delete:
        result = await tools["set_pool_entitlements"](
            pool_id="pool-1", pool_type="desktop", action="remove",
            ad_user_or_group_ids=["user-c"],
        )
    mock_delete.assert_called_once()
    mock_post.assert_not_called()
    mock_put.assert_not_called()
    assert result["action"] == "remove"


async def test_set_pool_entitlements_passes_correct_spec(tools):
    captured: dict = {}

    async def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return None

    with patch("horizon_mcp.tools.entitlements.api_post", side_effect=fake_post):
        await tools["set_pool_entitlements"](
            pool_id="pool-xyz", pool_type="desktop", action="add",
            ad_user_or_group_ids=["user-1", "group-2"],
        )

    assert captured["path"] == "/entitlements/v1/desktop-pools"
    assert captured["body"] == [{"id": "pool-xyz", "ad_user_or_group_ids": ["user-1", "group-2"]}]


@pytest.mark.parametrize("pool_type", ["desktop", "application"])
async def test_set_pool_entitlements_url_uses_pool_type_directly(tools, pool_type):
    captured: dict = {}

    async def fake_post(path, body):
        captured["path"] = path
        return None

    with patch("horizon_mcp.tools.entitlements.api_post", side_effect=fake_post):
        await tools["set_pool_entitlements"](
            pool_id="p1", pool_type=pool_type, action="add",
            ad_user_or_group_ids=["u1"],
        )

    assert captured["path"] == f"/entitlements/v1/{pool_type}-pools"
