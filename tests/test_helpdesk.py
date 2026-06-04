"""Tests for consolidated helpdesk.diagnose_session tool."""
import pytest
from unittest.mock import AsyncMock, patch

from .conftest import MockFastMCP
from horizon_mcp.tools import helpdesk
from horizon_mcp.tools.helpdesk import _DIAGNOSTIC_ASPECTS


@pytest.fixture
def tools(mock_mcp: MockFastMCP):
    helpdesk.register(mock_mcp)
    return mock_mcp.tools


# ── Constants ──────────────────────────────────────────────────────────────────

def test_diagnostic_aspects_keys():
    assert set(_DIAGNOSTIC_ASPECTS) == {
        "logon_timing",
        "display_performance",
        "historical_performance",
        "processes",
        "remote_applications",
    }


def test_diagnostic_aspects_have_paths_and_types():
    for key, (path, kind) in _DIAGNOSTIC_ASPECTS.items():
        assert path.startswith("/helpdesk/"), f"{key} has unexpected path: {path}"
        assert kind in ("dict", "list"), f"{key} has unexpected type: {kind}"


# ── diagnose_session ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_diagnose_session_all_aspects_called(tools):
    call_count = 0

    async def fake_api_get(path, params=None):
        nonlocal call_count
        call_count += 1
        return {"path": path}

    with patch("horizon_mcp.tools.helpdesk.api_get", side_effect=fake_api_get):
        result = await tools["diagnose_session"](session_id="sess-001")

    assert call_count == len(_DIAGNOSTIC_ASPECTS)
    assert set(result.keys()) == set(_DIAGNOSTIC_ASPECTS.keys())


@pytest.mark.asyncio
async def test_diagnose_session_subset_of_aspects(tools):
    call_count = 0

    async def fake_api_get(path, params=None):
        nonlocal call_count
        call_count += 1
        return {"timing": "data"}

    with patch("horizon_mcp.tools.helpdesk.api_get", side_effect=fake_api_get):
        result = await tools["diagnose_session"](
            session_id="sess-002",
            aspects=["logon_timing", "processes"],
        )

    assert call_count == 2
    assert set(result.keys()) == {"logon_timing", "processes"}


@pytest.mark.asyncio
async def test_diagnose_session_partial_failure_returns_error_string(tools):
    async def fake_api_get(path, params=None):
        if "logon-segment" in path:
            raise ValueError("Connection timeout")
        return {"fps": 30}

    with patch("horizon_mcp.tools.helpdesk.api_get", side_effect=fake_api_get):
        result = await tools["diagnose_session"](
            session_id="sess-003",
            aspects=["logon_timing", "display_performance"],
        )

    assert "Connection timeout" in result["logon_timing"]
    assert result["display_performance"] == {"fps": 30}


@pytest.mark.asyncio
async def test_diagnose_session_unknown_aspects_are_ignored(tools):
    call_count = 0

    async def fake_api_get(path, params=None):
        nonlocal call_count
        call_count += 1
        return {}

    with patch("horizon_mcp.tools.helpdesk.api_get", side_effect=fake_api_get):
        result = await tools["diagnose_session"](
            session_id="sess-004",
            aspects=["logon_timing", "not_a_real_aspect"],
        )

    assert call_count == 1
    assert "not_a_real_aspect" not in result


@pytest.mark.asyncio
async def test_diagnose_session_passes_session_id_to_each_call(tools):
    received_params = []

    async def fake_api_get(path, params=None):
        received_params.append(params)
        return {}

    with patch("horizon_mcp.tools.helpdesk.api_get", side_effect=fake_api_get):
        await tools["diagnose_session"](session_id="my-session-id", aspects=["logon_timing"])

    assert received_params == [{"session_id": "my-session-id"}]


@pytest.mark.asyncio
async def test_diagnose_session_none_result_returns_empty(tools):
    async def fake_api_get(path, params=None):
        return None

    with patch("horizon_mcp.tools.helpdesk.api_get", side_effect=fake_api_get):
        result = await tools["diagnose_session"](
            session_id="sess-005",
            aspects=["processes", "logon_timing"],
        )

    assert result["processes"] == []
    assert result["logon_timing"] == {}
