"""Tests for HTTP transport hardening: fail-closed startup and Host/Origin validation."""
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from horizon_mcp import __main__ as entry
from horizon_mcp.http_security import HostOriginGuard


def _client(monkeypatch, bind_host, allowed_hosts="", allowed_origins="", base_url="http://127.0.0.1:8000"):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", allowed_hosts)
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", allowed_origins)
    app = Starlette(
        routes=[Route("/mcp", lambda r: PlainTextResponse("ok"), methods=["GET", "POST"])],
        middleware=[Middleware(HostOriginGuard, bind_host=bind_host)],
    )
    return TestClient(app, base_url=base_url)


# ── startup ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("transport", ["streamable-http", "sse", "http"])
def test_http_transport_refuses_to_start_without_api_key(monkeypatch, transport):
    monkeypatch.setenv("MCP_TRANSPORT", transport)
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MCP_ALLOW_UNAUTHENTICATED", raising=False)
    with pytest.raises(SystemExit, match="MCP_API_KEY"):
        entry.main()


def test_stdio_starts_without_api_key(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr("horizon_mcp.server.mcp.run", lambda **kw: calls.append(kw))
    entry.main()
    assert calls == [{"transport": "stdio"}]


def test_http_opt_out_and_default_loopback_bind(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.setenv("MCP_ALLOW_UNAUTHENTICATED", "true")
    calls = []
    monkeypatch.setattr("horizon_mcp.server.mcp.run", lambda **kw: calls.append(kw))
    entry.main()
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["middleware"][0].cls is HostOriginGuard


# ── Host header ───────────────────────────────────────────────────────────────

def test_loopback_bind_accepts_loopback_host(monkeypatch):
    c = _client(monkeypatch, "127.0.0.1")
    for host in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000", "localhost"):
        assert c.get("/mcp", headers={"Host": host}).status_code == 200


def test_loopback_bind_rejects_rebound_host(monkeypatch):
    resp = _client(monkeypatch, "127.0.0.1", base_url="http://evil.example.com:8000").get("/mcp")
    assert resp.status_code == 421


def test_wildcard_bind_without_allowlist_does_not_check_host(monkeypatch):
    assert _client(monkeypatch, "0.0.0.0", base_url="http://mcp.corp.example.com").get("/mcp").status_code == 200


def test_explicit_allowed_hosts_are_enforced(monkeypatch):
    ok = _client(monkeypatch, "0.0.0.0", allowed_hosts="mcp.corp.example.com", base_url="http://mcp.corp.example.com")
    bad = _client(monkeypatch, "0.0.0.0", allowed_hosts="mcp.corp.example.com", base_url="http://other.example.com")
    assert ok.get("/mcp").status_code == 200
    assert bad.get("/mcp").status_code == 421


# ── Origin header ─────────────────────────────────────────────────────────────

def test_request_without_origin_is_allowed(monkeypatch):
    assert _client(monkeypatch, "0.0.0.0").post("/mcp").status_code == 200


def test_foreign_origin_is_rejected(monkeypatch):
    resp = _client(monkeypatch, "127.0.0.1").post("/mcp", headers={"Origin": "https://evil.example.com"})
    assert resp.status_code == 403


def test_loopback_origin_allowed_only_on_loopback_bind(monkeypatch):
    headers = {"Origin": "http://localhost:6274"}
    assert _client(monkeypatch, "127.0.0.1").post("/mcp", headers=headers).status_code == 200
    assert _client(monkeypatch, "0.0.0.0").post("/mcp", headers=headers).status_code == 403


def test_allowed_origins_env(monkeypatch):
    c = _client(monkeypatch, "0.0.0.0", allowed_origins="https://app.example.com")
    assert c.post("/mcp", headers={"Origin": "https://app.example.com"}).status_code == 200


def test_unknown_transport_is_rejected(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "websocket")
    with pytest.raises(SystemExit, match="Unknown MCP_TRANSPORT"):
        entry.main()
