"""Tests for the audit log: confirmation decisions, mutating API calls, no secrets, never stdout."""
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from .conftest import MockFastMCP
from .test_confirm import _Ctx, _Result, _with_ctx
from horizon_mcp import audit, client
from horizon_mcp.client import api_delete, api_get, api_post, api_put
from horizon_mcp.tools import auth
from horizon_mcp.tools._confirm import PROCEED, ConfirmationRequired, require_confirmation

FAKE_PASSWORD = "Fake-P4ssw0rd-do-not-log"
FAKE_TOKEN = "fake-access-token-do-not-log"
FAKE_REFRESH = "fake-refresh-token-do-not-log"


@pytest.fixture(autouse=True)
def audit_to_stderr(monkeypatch):
    monkeypatch.delenv("HORIZON_AUDIT_LOG", raising=False)
    yield
    monkeypatch.delenv("HORIZON_AUDIT_LOG", raising=False)
    audit._configure()  # don't leave a FileHandler pointing into tmp_path


def entries(capsys) -> list[dict]:
    """Audit lines written so far. Also asserts nothing went to stdout."""
    out, err = capsys.readouterr()
    assert out == ""
    return [json.loads(line) for line in err.splitlines() if line.startswith("{")]


# ── confirmation decisions ────────────────────────────────────────────────────

async def test_elicitation_approved_is_logged(capsys):
    with _with_ctx(_Ctx(result=_Result("accept", PROCEED))):
        await require_confirmation("Delete pool Sales (p1).")
    [e] = entries(capsys)
    assert e["event"] == "confirmation"
    assert e["outcome"] == "approved"
    assert e["method"] == "elicitation"
    assert e["summary"] == "Delete pool Sales (p1)"
    assert e["ts"].endswith("Z")


async def test_elicitation_cancelled_is_logged(capsys):
    with _with_ctx(_Ctx(result=_Result("decline"))):
        with pytest.raises(ConfirmationRequired):
            await require_confirmation("Delete pool Sales (p1)")
    [e] = entries(capsys)
    assert (e["outcome"], e["method"]) == ("cancelled", "elicitation")


async def test_refused_without_elicitation_is_logged(capsys, monkeypatch):
    monkeypatch.delenv("HORIZON_CONFIRMATION", raising=False)
    with _with_ctx(None):
        with pytest.raises(ConfirmationRequired):
            await require_confirmation("Delete pool Sales (p1)", confirm=True)
    [e] = entries(capsys)
    assert (e["outcome"], e["method"]) == ("refused", "no_elicitation")


@pytest.mark.parametrize("confirm,outcome", [(True, "approved"), (False, "missing_confirm")])
async def test_flag_mode_decisions_are_logged(capsys, monkeypatch, confirm, outcome):
    monkeypatch.setenv("HORIZON_CONFIRMATION", "flag")
    with _with_ctx(None):
        if confirm:
            await require_confirmation("Delete pool Sales (p1)", confirm=True)
        else:
            with pytest.raises(ConfirmationRequired):
                await require_confirmation("Delete pool Sales (p1)")
    [e] = entries(capsys)
    assert (e["outcome"], e["method"]) == (outcome, "confirm_flag")


async def test_tool_name_comes_from_middleware(capsys):
    async def call_next(context):
        with _with_ctx(_Ctx(result=_Result("accept", PROCEED))):
            await require_confirmation("Delete pool Sales (p1)")
        return "done"

    ctx = SimpleNamespace(message=SimpleNamespace(name="delete_desktop_pool"))
    assert await audit.ToolNameMiddleware().on_call_tool(ctx, call_next) == "done"
    audit.record("after")
    first, after = entries(capsys)
    assert first["tool"] == "delete_desktop_pool"
    assert after["tool"] is None


# ── API requests ──────────────────────────────────────────────────────────────

def _mock_client(monkeypatch, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.is_success = status_code < 400
    resp.content = b""
    resp.text = ""
    resp.json = MagicMock(return_value={})
    c = MagicMock()
    c.request = AsyncMock(return_value=resp)
    monkeypatch.setattr("horizon_mcp.client.get_client", AsyncMock(return_value=c))
    return c


@pytest.mark.parametrize("call,method", [
    (lambda: api_post("/inventory/v1/machines/action/restart", [{"password": FAKE_PASSWORD}]), "POST"),
    (lambda: api_put("/config/v1/settings", {"secret": FAKE_PASSWORD}), "PUT"),
    (lambda: api_delete("/inventory/v1/desktop-pools/p1", {"secret": FAKE_PASSWORD}), "DELETE"),
])
async def test_mutating_requests_are_logged_without_bodies(capsys, monkeypatch, call, method):
    _mock_client(monkeypatch, status_code=204)
    await call()
    out, err = capsys.readouterr()
    assert out == ""
    assert FAKE_PASSWORD not in err
    [e] = [json.loads(line) for line in err.splitlines()]
    assert e["event"] == "api_request"
    assert e["method"] == method
    assert e["status"] == 204
    assert e["retried"] is False


async def test_failed_mutating_request_is_logged_with_status(capsys, monkeypatch):
    _mock_client(monkeypatch, status_code=409)
    with pytest.raises(ValueError):
        await api_delete("/inventory/v1/desktop-pools/p1")
    [e] = entries(capsys)
    assert (e["method"], e["path"], e["status"]) == ("DELETE", "/inventory/v1/desktop-pools/p1", 409)


async def test_transport_error_is_logged_by_type(capsys, monkeypatch):
    c = _mock_client(monkeypatch)
    c.request.side_effect = httpx.ConnectError("unreachable")
    with pytest.raises(httpx.ConnectError):
        await api_post("/inventory/v1/desktop-pools/p1/action/disable")
    [e] = entries(capsys)
    assert e["error"] == "ConnectError"
    assert "status" not in e


async def test_get_requests_are_not_logged(capsys, monkeypatch):
    _mock_client(monkeypatch)
    await api_get("/inventory/v1/desktop-pools")
    assert entries(capsys) == []


async def test_audit_log_file(capsys, monkeypatch, tmp_path):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("HORIZON_AUDIT_LOG", str(log))
    _mock_client(monkeypatch)
    await api_delete("/inventory/v1/desktop-pools/p1")
    assert capsys.readouterr() == ("", "")
    [e] = [json.loads(line) for line in log.read_text().splitlines()]
    assert e["method"] == "DELETE"


# ── auth: logged, credentials never ───────────────────────────────────────────

def _auth_http(json_data, status_code=200):
    resp = MagicMock()
    resp.is_success = status_code < 400
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data)
    resp.text = str(json_data)
    http = AsyncMock()
    http.post = AsyncMock(return_value=resp)
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=http)


async def test_login_refresh_logout_are_logged_without_secrets(capsys, mock_mcp: MockFastMCP, monkeypatch):
    monkeypatch.setenv("HORIZON_EXPOSE_TOKENS", "true")  # even then, the log never sees tokens
    monkeypatch.setenv("HORIZON_ACCESS_TOKEN", "restored-after-test")
    auth.register(mock_mcp)
    tools = mock_mcp.tools
    tokens = {"access_token": FAKE_TOKEN, "refresh_token": FAKE_REFRESH}

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", _auth_http(tokens)):
        await tools["horizon_login"](username="jdoe", password=SecretStr(FAKE_PASSWORD), domain="EXAMPLE")
        await tools["horizon_refresh_token"]()
        await tools["horizon_logout"]()
    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", _auth_http({"error": "bad"}, status_code=401)):
        with pytest.raises(ValueError):
            await tools["horizon_login"](username="jdoe", password=SecretStr(FAKE_PASSWORD), domain="EXAMPLE")

    out, err = capsys.readouterr()
    assert out == ""
    for secret in (FAKE_PASSWORD, FAKE_TOKEN, FAKE_REFRESH, "jdoe", "Bearer"):
        assert secret not in err
    logged = [(e["action"], e["status"]) for e in map(json.loads, err.splitlines())]
    assert logged == [("login", 200), ("refresh", 200), ("logout", 200), ("login", 401)]


async def test_automatic_refresh_is_logged_without_secrets(capsys, monkeypatch):
    monkeypatch.setenv("HORIZON_ACCESS_TOKEN", "expired-" + FAKE_TOKEN)
    client.set_refresh_token(FAKE_REFRESH)
    ok, expired = MagicMock(spec=httpx.Response), MagicMock(spec=httpx.Response)
    ok.status_code, ok.is_success, ok.content = 200, True, b""
    expired.status_code, expired.is_success = 401, False
    c = MagicMock()
    c.request = AsyncMock(side_effect=[expired, ok])
    monkeypatch.setattr("horizon_mcp.client.get_client", AsyncMock(return_value=c))

    with patch("horizon_mcp.client.httpx.AsyncClient", _auth_http({"access_token": FAKE_TOKEN})):
        await api_post("/inventory/v1/desktop-pools/p1/action/disable")

    out, err = capsys.readouterr()
    assert out == ""
    assert FAKE_TOKEN not in err and FAKE_REFRESH not in err
    refresh, request = map(json.loads, err.splitlines())
    assert (refresh["event"], refresh["action"], refresh["trigger"]) == ("auth", "refresh", "auto")
    assert (request["event"], request["status"], request["retried"]) == ("api_request", 200, True)
    assert os.environ["HORIZON_ACCESS_TOKEN"] == FAKE_TOKEN
