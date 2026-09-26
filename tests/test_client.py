"""Tests for client.py: _parse_error, _reject_traversal, seg, get_client env validation, reset_client,
automatic token refresh on 401."""
import asyncio
import os
import subprocess
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from horizon_mcp import client as client_mod
from horizon_mcp.client import (
    _parse_error,
    _reject_traversal,
    api_delete,
    api_get,
    api_post,
    api_put,
    get_client,
    reset_client,
    seg,
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


@pytest.mark.parametrize(
    "path",
    [
        "/inventory/v1/desktop-pools/abc?x=1",
        "/inventory/v1/farms/abc#/rest",
        "/inventory/v1/farms/abc\\..\\config",
    ],
)
def test_reject_traversal_blocks_query_fragment_backslash(path):
    with pytest.raises(ValueError, match="Invalid request path"):
        _reject_traversal(path)


# ── seg ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value",
    ["3f2b1c9e-8d7a-4e6f-9b0c-1a2b3c4d5e6f", "S-1-5-32-544", "vm-2001", "farm.prod.01"],
)
def test_seg_leaves_real_horizon_ids_unchanged(value):
    assert seg(value) == value


@pytest.mark.parametrize(
    "value,expected",
    [
        ("../../config/v1/roles/x", "..%2F..%2Fconfig%2Fv1%2Froles%2Fx"),
        ("a?x=1", "a%3Fx%3D1"),
        ("a#b", "a%23b"),
        ("..;", "..%3B"),
        ("%2e%2e", "%252e%252e"),
    ],
)
def test_seg_encodes_everything_that_could_change_the_path(value, expected):
    assert seg(value) == expected


@pytest.mark.parametrize("value", ["", ".", ".."])
def test_seg_rejects_empty_and_dot_ids(value):
    with pytest.raises(ValueError, match="Invalid ID"):
        seg(value)


def test_seg_encoded_traversal_id_is_still_rejected_by_guard():
    with pytest.raises(ValueError, match="dot-segment"):
        _reject_traversal(f"/inventory/v1/desktop-pools/{seg('../../config')}")


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


def _transport_verifies_certs(client: httpx.AsyncClient) -> bool:
    """Introspect the actual SSL context an AsyncHTTPTransport was built with.

    Passing verify= to AsyncClient alone doesn't work once an explicit transport=
    is also supplied — the transport's own (default True) verify setting silently
    wins. Checking client.verify (or the value passed in) would miss that bug
    entirely; only the transport's real SSL context tells the truth.
    """
    import ssl
    return client._transport._pool._ssl_context.verify_mode != ssl.CERT_NONE


async def test_get_client_transport_actually_disables_verification_when_configured():
    with patch.dict(os.environ, {
        "HORIZON_BASE_URL": "https://horizon.test.example.com",
        "HORIZON_ACCESS_TOKEN": "test-token",
        "HORIZON_VERIFY_SSL": "false",
    }):
        client = await get_client()
    assert not _transport_verifies_certs(client), (
        "HORIZON_VERIFY_SSL=false did not disable verification on the actual transport"
    )


async def test_get_client_transport_verifies_certs_by_default():
    with patch.dict(os.environ, {
        "HORIZON_BASE_URL": "https://horizon.test.example.com",
        "HORIZON_ACCESS_TOKEN": "test-token",
    }, clear=False):
        os.environ.pop("HORIZON_VERIFY_SSL", None)
        client = await get_client()
    assert _transport_verifies_certs(client)


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


# ── automatic token refresh on 401 ─────────────────────────────────────────────

def _resp(status_code, json_data=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.is_success = status_code < 400
    resp.content = b"{}" if json_data is not None else b""
    resp.json = MagicMock(return_value=json_data)
    resp.text = str(json_data)
    return resp


def _refresh_endpoint(json_data, status_code=200, delay=0.0):
    """Mock httpx.AsyncClient serving POST /rest/refresh; returns (class, instance)."""
    async def post(url, json=None, **kwargs):
        await asyncio.sleep(delay)
        return _resp(status_code, json_data)

    http = AsyncMock()
    http.post = AsyncMock(side_effect=post)
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=http), http


def _horizon(monkeypatch, valid_token="new-token"):
    """Mock shared client that only accepts valid_token (the env token at send time)."""
    async def request(method, path, **kwargs):
        sent_with = os.environ.get("HORIZON_ACCESS_TOKEN")
        await asyncio.sleep(0.01)  # let concurrent callers all send before any refresh lands
        return _resp(200, {"ok": True}) if sent_with == valid_token else _resp(401, {"error_message": "expired"})

    client = MagicMock()
    client.request = AsyncMock(side_effect=request)
    monkeypatch.setattr("horizon_mcp.client.get_client", AsyncMock(return_value=client))
    return client


@pytest.fixture
def expired_session(monkeypatch):
    monkeypatch.setenv("HORIZON_ACCESS_TOKEN", "old-token")
    monkeypatch.setenv("HORIZON_BASE_URL", "https://horizon.test.example.com")


async def test_401_refreshes_token_and_retries_once(monkeypatch, expired_session):
    client_mod.set_refresh_token("stored-refresh")
    horizon = _horizon(monkeypatch)
    mock_class, http = _refresh_endpoint({"access_token": "new-token"})

    with patch("horizon_mcp.client.httpx.AsyncClient", mock_class):
        result = await api_get("/inventory/v1/desktop-pools")

    assert result == {"ok": True}
    assert horizon.request.await_count == 2
    http.post.assert_awaited_once()
    assert http.post.call_args.args[0] == "https://horizon.test.example.com/rest/refresh"
    assert http.post.call_args.kwargs["json"] == {"refresh_token": "stored-refresh"}
    assert os.environ["HORIZON_ACCESS_TOKEN"] == "new-token"


async def test_401_refresh_keeps_rotated_refresh_token(monkeypatch, expired_session):
    client_mod.set_refresh_token("stored-refresh")
    _horizon(monkeypatch)
    mock_class, _ = _refresh_endpoint({"access_token": "new-token", "refresh_token": "rotated-refresh"})

    with patch("horizon_mcp.client.httpx.AsyncClient", mock_class):
        await api_post("/inventory/v1/desktop-pools/p1/action/enable")

    assert client_mod.get_refresh_token() == "rotated-refresh"


async def test_concurrent_401s_trigger_a_single_refresh(monkeypatch, expired_session):
    client_mod.set_refresh_token("stored-refresh")
    horizon = _horizon(monkeypatch)
    mock_class, http = _refresh_endpoint({"access_token": "new-token"}, delay=0.02)

    with patch("horizon_mcp.client.httpx.AsyncClient", mock_class):
        results = await asyncio.gather(*(api_get(f"/inventory/v1/machines/m{i}") for i in range(5)))

    assert results == [{"ok": True}] * 5
    http.post.assert_awaited_once()
    assert horizon.request.await_count == 10


async def test_401_with_failed_refresh_raises_clear_error_without_looping(monkeypatch, expired_session):
    client_mod.set_refresh_token("stale-refresh")
    horizon = _horizon(monkeypatch)
    mock_class, http = _refresh_endpoint({"error_message": "refresh token expired"}, status_code=401)

    with patch("horizon_mcp.client.httpx.AsyncClient", mock_class):
        with pytest.raises(ValueError, match="couldn't be refreshed automatically.*horizon_login"):
            await api_get("/inventory/v1/desktop-pools")
        # The rejected refresh token is dropped, so the next call fails fast.
        with pytest.raises(ValueError, match="no refresh token.*horizon_login"):
            await api_get("/inventory/v1/desktop-pools")

    http.post.assert_awaited_once()
    assert horizon.request.await_count == 2
    assert client_mod.get_refresh_token() is None


async def test_refresh_network_error_keeps_refresh_token(monkeypatch, expired_session):
    client_mod.set_refresh_token("stored-refresh")
    _horizon(monkeypatch)
    mock_class, http = _refresh_endpoint({})
    http.post.side_effect = httpx.ConnectError("unreachable")

    with patch("horizon_mcp.client.httpx.AsyncClient", mock_class):
        with pytest.raises(ValueError, match="couldn't be refreshed automatically.*horizon_login"):
            await api_get("/inventory/v1/desktop-pools")

    assert client_mod.get_refresh_token() == "stored-refresh"


async def test_401_after_refresh_is_not_retried_again(monkeypatch, expired_session):
    client_mod.set_refresh_token("stored-refresh")
    horizon = _horizon(monkeypatch, valid_token="never-valid")
    mock_class, http = _refresh_endpoint({"access_token": "new-token"})

    with patch("horizon_mcp.client.httpx.AsyncClient", mock_class):
        with pytest.raises(ValueError, match=r"failed \(401\).*Still rejected.*horizon_login"):
            await api_get("/inventory/v1/desktop-pools")

    http.post.assert_awaited_once()
    assert horizon.request.await_count == 2


async def test_401_without_refresh_token_raises_clear_error(monkeypatch, expired_session):
    horizon = _horizon(monkeypatch)
    mock_class, http = _refresh_endpoint({"access_token": "new-token"})

    with patch("horizon_mcp.client.httpx.AsyncClient", mock_class):
        with pytest.raises(ValueError, match="no refresh token.*horizon_login"):
            await api_delete("/inventory/v1/desktop-pools/p1")

    http.post.assert_not_called()
    assert horizon.request.await_count == 1


async def test_missing_access_token_is_obtained_from_refresh_token(monkeypatch, expired_session):
    monkeypatch.delenv("HORIZON_ACCESS_TOKEN")
    client_mod.set_refresh_token("stored-refresh")
    horizon = _horizon(monkeypatch)
    mock_class, http = _refresh_endpoint({"access_token": "new-token"})

    with patch("horizon_mcp.client.httpx.AsyncClient", mock_class):
        assert await api_get("/inventory/v1/desktop-pools") == {"ok": True}

    http.post.assert_awaited_once()
    assert horizon.request.await_count == 1


def test_refresh_token_is_read_from_env_at_startup():
    env = {**os.environ, "HORIZON_REFRESH_TOKEN": "env-refresh-token"}
    out = subprocess.run(
        [sys.executable, "-c", "from horizon_mcp import client; print(client.get_refresh_token())"],
        env=env, capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "env-refresh-token"
