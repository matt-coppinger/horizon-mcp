"""Tests for client.py: _parse_error, _reject_traversal, get_client env validation, reset_client."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from horizon_mcp.client import (
    _parse_error,
    _reject_traversal,
    api_delete,
    api_get,
    api_post,
    api_put,
    get_client,
    reset_client,
)


@pytest.fixture(autouse=True)
async def clean_client():
    await reset_client()
    yield
    await reset_client()


def make_response(json_data=None, text="", status_code=400):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("not json"))
    return resp


# ── _parse_error ───────────────────────────────────────────────────────────────

def test_parse_error_uses_errors_field():
    resp = make_response(json_data={"errors": "session not found"})
    assert _parse_error(resp) == "session not found"


def test_parse_error_errors_list_is_stringified():
    resp = make_response(json_data={"errors": ["err1", "err2"]})
    result = _parse_error(resp)
    assert isinstance(result, str)
    assert "err1" in result


def test_parse_error_uses_error_message_field():
    resp = make_response(json_data={"error_message": "bad token"})
    assert _parse_error(resp) == "bad token"


def test_parse_error_uses_message_field():
    resp = make_response(json_data={"message": "resource not found"})
    assert _parse_error(resp) == "resource not found"


def test_parse_error_falls_back_to_full_body():
    resp = make_response(json_data={"code": 404, "unknown_field": "data"})
    result = _parse_error(resp)
    assert isinstance(result, str)
    assert len(result) > 0


def test_parse_error_non_json_uses_text():
    resp = make_response(text="Service Unavailable")
    assert _parse_error(resp) == "Service Unavailable"


def test_parse_error_empty_text_uses_status_code():
    resp = make_response(text="", status_code=503)
    result = _parse_error(resp)
    assert "503" in result


# ── _reject_traversal ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path",
    [
        "/inventory/v1/desktop-pools/../../../config/v1/global-policies",
        "/inventory/v1/farms/..%2f..%2fconfig/v1/global-policies",
        "/inventory/v1/farms/%2e%2e/%2e%2e/config/v1/global-policies",
        "/inventory/v1/machines/./action/foo",
    ],
)
def test_reject_traversal_blocks_dot_segments(path):
    with pytest.raises(ValueError, match="dot-segment"):
        _reject_traversal(path)


@pytest.mark.parametrize(
    "path",
    [
        "/inventory/v1/desktop-pools/abc-123",
        "/inventory/v1/farms/farm.prod.01",
        "/entitlements/v1/desktop-pools",
    ],
)
def test_reject_traversal_allows_normal_paths(path):
    _reject_traversal(path)  # should not raise


async def _mock_client(monkeypatch, method: str):
    resp = MagicMock(spec=httpx.Response)
    resp.is_success = True
    resp.content = b""
    client = MagicMock()
    setattr(client, method, AsyncMock(return_value=resp))
    client.request = AsyncMock(return_value=resp)
    monkeypatch.setattr("horizon_mcp.client.get_client", AsyncMock(return_value=client))
    return client


async def test_api_get_raises_before_dispatch_on_traversal(monkeypatch):
    client = await _mock_client(monkeypatch, "get")
    with pytest.raises(ValueError, match="dot-segment"):
        await api_get("/inventory/v1/desktop-pools/../../config/v1/global-policies")
    client.get.assert_not_called()


async def test_api_put_raises_before_dispatch_on_traversal(monkeypatch):
    client = await _mock_client(monkeypatch, "put")
    with pytest.raises(ValueError, match="dot-segment"):
        await api_put("/inventory/v1/desktop-pools/../../config/v1/global-policies", {"evil": "spec"})
    client.put.assert_not_called()


async def test_api_delete_raises_before_dispatch_on_traversal(monkeypatch):
    client = await _mock_client(monkeypatch, "delete")
    with pytest.raises(ValueError, match="dot-segment"):
        await api_delete("/inventory/v1/farms/../../config/v1/global-policies")
    client.request.assert_not_called()


async def test_api_post_raises_before_dispatch_on_traversal(monkeypatch):
    client = await _mock_client(monkeypatch, "post")
    with pytest.raises(ValueError, match="dot-segment"):
        await api_post("/inventory/v1/machines/../../config/v1/global-policies/action/x")
    client.post.assert_not_called()


# ── get_client ─────────────────────────────────────────────────────────────────

async def test_get_client_raises_without_base_url():
    with patch.dict(os.environ, {"HORIZON_BASE_URL": "", "HORIZON_ACCESS_TOKEN": "tok"}):
        with pytest.raises(ValueError, match="HORIZON_BASE_URL"):
            await get_client()


async def test_get_client_raises_without_token():
    with patch.dict(os.environ, {"HORIZON_BASE_URL": "https://h.test", "HORIZON_ACCESS_TOKEN": ""}):
        with pytest.raises(ValueError, match="HORIZON_ACCESS_TOKEN"):
            await get_client()


async def test_get_client_returns_same_instance_on_repeated_calls():
    with patch.dict(os.environ, {
        "HORIZON_BASE_URL": "https://horizon.test.example.com",
        "HORIZON_ACCESS_TOKEN": "test-token",
        "HORIZON_VERIFY_SSL": "false",
    }):
        client1 = await get_client()
        client2 = await get_client()
    assert client1 is client2


# ── reset_client ───────────────────────────────────────────────────────────────

async def test_reset_client_idempotent():
    await reset_client()
    await reset_client()  # should not raise


async def test_reset_client_forces_new_instance():
    with patch.dict(os.environ, {
        "HORIZON_BASE_URL": "https://horizon.test.example.com",
        "HORIZON_ACCESS_TOKEN": "test-token",
        "HORIZON_VERIFY_SSL": "false",
    }):
        client1 = await get_client()
        await reset_client()
        client2 = await get_client()
    assert client1 is not client2
