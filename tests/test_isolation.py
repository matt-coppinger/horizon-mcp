"""Multi-user mode: every identity has its own Horizon session, and nothing leaks between them.

The authenticated identity is normally the client_id FastMCP puts on the request's access
token; here a context variable stands in for it (test_multiuser_http.py covers the real
HTTP path end to end). Horizon is FakeHorizon, which records the Authorization header of
every request, so the assertions are about the tokens actually sent.
"""
import asyncio
import contextvars
import inspect
import json

import pytest
from pydantic import SecretStr

from horizon_mcp import client, identity
from horizon_mcp.client import api_get, api_post
from horizon_mcp.identity import IdentityError
from horizon_mcp.tools import auth

from .conftest import MockFastMCP
from .fake_horizon import FakeHorizon

_caller: contextvars.ContextVar[str | None] = contextvars.ContextVar("test_caller", default=None)


@pytest.fixture
def horizon(monkeypatch) -> FakeHorizon:
    monkeypatch.setattr(identity, "_authenticated_name", lambda: _caller.get())
    client.configure(multi_user=True)
    return FakeHorizon().install(monkeypatch)


@pytest.fixture
def tools(mock_mcp: MockFastMCP):
    auth.register(mock_mcp)
    return mock_mcp.tools


async def as_user(name, fn, *args, **kwargs):
    token = _caller.set(name)
    try:
        result = fn(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result
    finally:
        _caller.reset(token)


async def login(tools, name, ad_user=None):
    ad_user = ad_user or name
    return await as_user(name, tools["horizon_login"], username=ad_user, password=SecretStr(f"pw-{ad_user}"), domain="EXAMPLE")


async def test_user_who_has_not_logged_in_is_told_to_log_in_and_sends_nothing(horizon, tools):
    await login(tools, "alice")
    with pytest.raises(ValueError, match="horizon_login"):
        await as_user("bob", api_get, "/inventory/v1/desktop-pools")
    assert horizon.requests == []  # bob's call never reached Horizon, with anyone's token


async def test_each_user_calls_horizon_with_their_own_token(horizon, tools):
    await login(tools, "alice")
    await login(tools, "bob")
    a = await as_user("alice", api_get, "/inventory/v1/desktop-pools")
    b = await as_user("bob", api_get, "/inventory/v1/desktop-pools")
    assert a == [{"id": "pool-of-alice", "name": "Pool of alice"}]
    assert b == [{"id": "pool-of-bob", "name": "Pool of bob"}]
    alice_tok, bob_tok = horizon.tokens_sent()
    assert alice_tok.startswith("Bearer at-alice-") and bob_tok.startswith("Bearer at-bob-")


async def test_unauthenticated_request_fails_closed_in_multi_user_mode(horizon, tools):
    await login(tools, "alice")
    with pytest.raises(IdentityError, match="no authenticated user"):
        await api_get("/inventory/v1/desktop-pools")
    with pytest.raises(IdentityError):
        await tools["horizon_login"](username="alice", password=SecretStr("pw-alice"), domain="EXAMPLE")
    assert horizon.requests == []


async def test_logout_ends_only_the_callers_session(horizon, tools):
    await login(tools, "alice")
    await login(tools, "bob")
    bob_refresh = await as_user("bob", client.get_refresh_token)

    assert await as_user("alice", tools["horizon_logout"]) == {"logged_out": True}

    assert len(horizon.logouts) == 1 and horizon.logouts[0].startswith("rt-alice-")
    with pytest.raises(ValueError, match="horizon_login"):
        await as_user("alice", api_get, "/inventory/v1/desktop-pools")
    assert await as_user("bob", api_get, "/inventory/v1/desktop-pools") == [{"id": "pool-of-bob", "name": "Pool of bob"}]
    assert await as_user("bob", client.get_refresh_token) == bob_refresh
    assert "alice" not in client._sessions  # the logged-out session is freed


async def test_refresh_and_logout_tools_use_only_the_callers_refresh_token(horizon, tools):
    await login(tools, "alice")
    await login(tools, "bob")
    with pytest.raises(ValueError, match="horizon_login"):
        await as_user("carol", tools["horizon_refresh_token"])
    with pytest.raises(ValueError, match="horizon_login"):
        await as_user("carol", tools["horizon_logout"])
    await as_user("bob", tools["horizon_refresh_token"])
    assert len(horizon.refresh_calls) == 1 and horizon.refresh_calls[0].startswith("rt-bob-")
    assert horizon.logouts == []


async def test_401_refresh_renews_only_that_users_token(horizon, tools):
    await login(tools, "alice")
    await login(tools, "bob")
    bob_before = (await as_user("bob", client.current_session)).access_token
    horizon.expire("alice")

    assert await as_user("alice", api_get, "/inventory/v1/desktop-pools")
    await as_user("bob", api_get, "/inventory/v1/desktop-pools")

    assert len(horizon.refresh_calls) == 1 and horizon.refresh_calls[0].startswith("rt-alice-")
    assert (await as_user("bob", client.current_session)).access_token == bob_before
    assert horizon.tokens_sent()[-1] == f"Bearer {bob_before}"


async def test_dead_refresh_token_ends_only_that_users_session(horizon, tools):
    await login(tools, "alice")
    await login(tools, "bob")
    horizon.expire("alice")
    horizon.revoke_refresh("alice")

    with pytest.raises(ValueError, match="couldn't be refreshed automatically.*horizon_login"):
        await as_user("alice", api_get, "/inventory/v1/desktop-pools")
    assert "alice" not in client._sessions
    with pytest.raises(ValueError, match="horizon_login"):
        await as_user("alice", api_get, "/inventory/v1/desktop-pools")
    assert await as_user("bob", api_get, "/inventory/v1/desktop-pools")


async def test_concurrent_calls_each_use_their_own_token(horizon, tools):
    await login(tools, "alice")
    await login(tools, "bob")
    horizon.delay = 0.01  # interleave the requests
    users = ["alice", "bob"] * 5
    results = await asyncio.gather(*(as_user(u, api_get, "/inventory/v1/desktop-pools") for u in users))
    assert [r[0]["id"] for r in results] == [f"pool-of-{u}" for u in users]
    assert sorted(t.split("-")[1] for t in horizon.tokens_sent()) == ["alice"] * 5 + ["bob"] * 5


async def test_concurrent_401s_refresh_once_per_user_independently(horizon, tools):
    await login(tools, "alice")
    await login(tools, "bob")
    horizon.expire("alice")
    horizon.expire("bob")
    horizon.delay = 0.01
    users = ["alice", "bob"] * 4
    results = await asyncio.gather(*(as_user(u, api_post, "/inventory/v1/desktop-pools/p1/action/enable") for u in users))
    assert results == [None] * 8
    assert sorted(t.split("-")[1] for t in horizon.refresh_calls) == ["alice", "bob"]


async def test_same_ad_account_is_still_two_separate_sessions(horizon, tools):
    # Two API keys that happen to log in as the same AD user still get separate sessions.
    await login(tools, "alice", ad_user="svc")
    await login(tools, "bob", ad_user="svc")
    a = await as_user("alice", client.current_session)
    b = await as_user("bob", client.current_session)
    assert a is not b and a.access_token != b.access_token


async def test_session_repr_never_shows_tokens(horizon, tools):
    await login(tools, "alice")
    s = await as_user("alice", client.current_session)
    assert s.access_token and s.access_token not in repr(s) and s.refresh_token not in repr(s)


async def test_audit_lines_name_the_calling_user(horizon, tools, capsys):
    await login(tools, "alice")
    await login(tools, "bob")
    capsys.readouterr()
    await as_user("alice", api_post, "/inventory/v1/desktop-pools/p1/action/disable")
    await as_user("bob", tools["horizon_logout"])
    _, err = capsys.readouterr()
    lines = [json.loads(line) for line in err.splitlines() if line.startswith("{")]
    assert [(e["event"], e["user"]) for e in lines] == [("api_request", "alice"), ("auth", "bob")]
    for e in lines:
        assert "at-" not in json.dumps(e) and "rt-" not in json.dumps(e)


async def test_single_user_mode_always_uses_the_one_session(monkeypatch):
    # stdio / MCP_API_KEY: no per-request identity; env tokens seed the single user.
    monkeypatch.setattr(identity, "_authenticated_name", lambda: "someone-else")
    client.configure(multi_user=False, single_user=identity.DEFAULT, access_token="seeded", refresh_token="seeded-rt")
    s = client.current_session()
    assert (s.identity, s.access_token, s.refresh_token) == ("default", "seeded", "seeded-rt")


def test_multi_user_mode_never_seeds_a_shared_token():
    with pytest.raises(ValueError, match="shared"):
        client.configure(multi_user=True, access_token="shared")
