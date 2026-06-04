"""Tests for consolidated monitor tools: get_infrastructure_health and get_metrics."""
import pytest
from unittest.mock import patch

from .conftest import MockFastMCP
from horizon_mcp.tools import monitor
from horizon_mcp.tools.monitor import _HEALTH_ENDPOINTS, _METRICS_ENDPOINTS


@pytest.fixture
def tools(mock_mcp: MockFastMCP):
    monitor.register(mock_mcp)
    return mock_mcp.tools


# ── Constants ──────────────────────────────────────────────────────────────────

def test_health_endpoint_keys():
    assert set(_HEALTH_ENDPOINTS) == {
        "summary", "connection_servers", "gateways",
        "virtual_centers", "ad_domains", "farms",
    }


def test_metrics_endpoint_keys():
    assert set(_METRICS_ENDPOINTS) == {
        "pools", "sessions", "machines", "system", "rds_servers", "license",
    }


def test_all_health_paths_start_with_monitor():
    for key, path in _HEALTH_ENDPOINTS.items():
        assert path.startswith("/monitor/"), f"{key}: unexpected path {path}"


def test_all_metrics_paths_start_with_monitor():
    for key, path in _METRICS_ENDPOINTS.items():
        assert path.startswith("/monitor/"), f"{key}: unexpected path {path}"


# ── get_infrastructure_health ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_infrastructure_health_all_components(tools):
    call_count = 0

    async def fake_api_get(path, params=None):
        nonlocal call_count
        call_count += 1
        return [{"status": "OK"}]

    with patch("horizon_mcp.tools.monitor.api_get", side_effect=fake_api_get):
        result = await tools["get_infrastructure_health"]()

    assert call_count == len(_HEALTH_ENDPOINTS)
    assert set(result.keys()) == set(_HEALTH_ENDPOINTS.keys())


@pytest.mark.asyncio
async def test_get_infrastructure_health_subset(tools):
    call_count = 0

    async def fake_api_get(path, params=None):
        nonlocal call_count
        call_count += 1
        return []

    with patch("horizon_mcp.tools.monitor.api_get", side_effect=fake_api_get):
        result = await tools["get_infrastructure_health"](components=["summary", "gateways"])

    assert call_count == 2
    assert set(result.keys()) == {"summary", "gateways"}


@pytest.mark.asyncio
async def test_get_infrastructure_health_partial_failure(tools):
    async def fake_api_get(path, params=None):
        if "health-metrics" in path:
            raise ValueError("503 Service Unavailable")
        return [{"ok": True}]

    with patch("horizon_mcp.tools.monitor.api_get", side_effect=fake_api_get):
        result = await tools["get_infrastructure_health"](components=["summary", "gateways"])

    assert "503 Service Unavailable" in result["summary"]
    assert result["gateways"] == [{"ok": True}]


@pytest.mark.asyncio
async def test_get_infrastructure_health_unknown_components_ignored(tools):
    call_count = 0

    async def fake_api_get(path, params=None):
        nonlocal call_count
        call_count += 1
        return []

    with patch("horizon_mcp.tools.monitor.api_get", side_effect=fake_api_get):
        result = await tools["get_infrastructure_health"](
            components=["summary", "not_a_component"]
        )

    assert call_count == 1
    assert "not_a_component" not in result


# ── get_metrics ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_metrics_all_scopes(tools):
    call_count = 0

    async def fake_api_get(path, params=None):
        nonlocal call_count
        call_count += 1
        return {"count": 42}

    with patch("horizon_mcp.tools.monitor.api_get", side_effect=fake_api_get):
        result = await tools["get_metrics"]()

    assert call_count == len(_METRICS_ENDPOINTS)
    assert set(result.keys()) == set(_METRICS_ENDPOINTS.keys())


@pytest.mark.asyncio
async def test_get_metrics_subset(tools):
    call_count = 0

    async def fake_api_get(path, params=None):
        nonlocal call_count
        call_count += 1
        return {"connected": 10}

    with patch("horizon_mcp.tools.monitor.api_get", side_effect=fake_api_get):
        result = await tools["get_metrics"](scope=["sessions", "license"])

    assert call_count == 2
    assert set(result.keys()) == {"sessions", "license"}


@pytest.mark.asyncio
async def test_get_metrics_none_result_returns_empty_dict(tools):
    async def fake_api_get(path, params=None):
        return None

    with patch("horizon_mcp.tools.monitor.api_get", side_effect=fake_api_get):
        result = await tools["get_metrics"](scope=["sessions"])

    assert result["sessions"] == {}


@pytest.mark.asyncio
async def test_get_metrics_partial_failure(tools):
    async def fake_api_get(path, params=None):
        if "sessions" in path:
            raise ValueError("timeout")
        return {"count": 5}

    with patch("horizon_mcp.tools.monitor.api_get", side_effect=fake_api_get):
        result = await tools["get_metrics"](scope=["sessions", "pools"])

    assert "timeout" in result["sessions"]
    assert result["pools"] == {"count": 5}
