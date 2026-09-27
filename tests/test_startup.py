"""Startup modes: which auth mode the server runs in, and the configurations it refuses."""
import json

import pytest

from horizon_mcp import __main__ as entry
from horizon_mcp import client, identity
from horizon_mcp.__main__ import Mode, StartupError, resolve_mode
from horizon_mcp.users import hash_key

BASE = {"HORIZON_BASE_URL": "https://horizon.test.example.com"}


@pytest.fixture
def users_file(tmp_path):
    f = tmp_path / "users.json"
    f.write_text(json.dumps({"users": [{"name": "alice", "key_sha256": hash_key("k1")}]}))
    return str(f)


def test_stdio_is_single_local_user():
    assert resolve_mode("stdio", {"MCP_API_KEY": "ignored"}) == Mode("stdio", "local")


def test_stdio_refuses_a_users_file(users_file):
    with pytest.raises(StartupError, match="only applies to HTTP"):
        resolve_mode("stdio", {**BASE, "MCP_USERS_FILE": users_file})


@pytest.mark.parametrize("transport", ["streamable-http", "sse", "http"])
def test_http_with_api_key_is_single_user_default(transport):
    assert resolve_mode(transport, {"MCP_API_KEY": "k"}) == Mode("single", "default")


def test_http_with_users_file_is_multi_user(users_file):
    assert resolve_mode("streamable-http", {**BASE, "MCP_USERS_FILE": users_file}).kind == "multi"


def test_both_key_modes_are_refused(users_file):
    with pytest.raises(StartupError, match="not both"):
        resolve_mode("streamable-http", {**BASE, "MCP_USERS_FILE": users_file, "MCP_API_KEY": "k"})


@pytest.mark.parametrize("var", ["HORIZON_ACCESS_TOKEN", "HORIZON_REFRESH_TOKEN"])
def test_multi_user_refuses_a_shared_horizon_token(users_file, var):
    with pytest.raises(StartupError, match=f"{var}.*shared by every user"):
        resolve_mode("streamable-http", {**BASE, "MCP_USERS_FILE": users_file, var: "tok"})


def test_multi_user_requires_base_url(users_file):
    with pytest.raises(StartupError, match="requires HORIZON_BASE_URL"):
        resolve_mode("streamable-http", {"MCP_USERS_FILE": users_file})


def test_multi_user_refuses_allow_unauthenticated(users_file):
    with pytest.raises(StartupError, match="MCP_ALLOW_UNAUTHENTICATED"):
        resolve_mode("streamable-http", {**BASE, "MCP_USERS_FILE": users_file, "MCP_ALLOW_UNAUTHENTICATED": "true"})


@pytest.mark.parametrize("content,match", [
    (None, "does not exist"),
    ("{", "not valid JSON"),
    ('{"users": []}', "no users"),
    ('{"users": [{"name": "alice", "key_sha256": "plaintext-key"}]}', "key_sha256"),
])
def test_invalid_users_file_is_refused(tmp_path, content, match):
    f = tmp_path / "users.json"
    if content is not None:
        f.write_text(content)
    with pytest.raises(StartupError, match=f"Refusing to start: .*{match}"):
        resolve_mode("streamable-http", {**BASE, "MCP_USERS_FILE": str(f)})


def test_http_without_any_key_is_refused():
    with pytest.raises(StartupError, match="MCP_API_KEY or MCP_USERS_FILE"):
        resolve_mode("streamable-http", {})


def test_unknown_transport_is_refused():
    with pytest.raises(StartupError, match="Unknown MCP_TRANSPORT"):
        resolve_mode("carrier-pigeon", {})


def test_main_exits_with_the_startup_message(monkeypatch, users_file):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_USERS_FILE", users_file)
    monkeypatch.setenv("HORIZON_ACCESS_TOKEN", "shared")
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="shared by every user"):
        entry.main()


def test_single_user_modes_seed_the_session_from_env():
    entry.configure_sessions(Mode("single", "default"), {"HORIZON_ACCESS_TOKEN": "a", "HORIZON_REFRESH_TOKEN": "r"})
    assert not identity.is_multi_user()
    s = client.current_session()
    assert (s.identity, s.access_token, s.refresh_token) == ("default", "a", "r")


def test_multi_user_mode_starts_with_no_sessions():
    entry.configure_sessions(Mode("multi", "default"), {})
    assert identity.is_multi_user()
    assert client._sessions == {}
