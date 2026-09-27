"""Multi-user mode end to end: real HTTP transport, FastMCP's auth middleware, two API keys.

The server runs on a random localhost port (uvicorn, in-process). Two MCP clients connect
with different keys and drive the tools over the MCP protocol; Horizon is FakeHorizon,
so the test sees exactly which Horizon token every request carried.
"""
import json

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.utilities.tests import run_server_async

from horizon_mcp import client
from horizon_mcp.server import create_server
from horizon_mcp.users import ApiKeyVerifier, hash_key

from .fake_horizon import FakeHorizon

ALICE_KEY = "test-key-alice-not-a-real-key"
BOB_KEY = "test-key-bob-not-a-real-key"
_ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
_INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}


@pytest.fixture
async def server(monkeypatch):
    monkeypatch.undo()  # the real require_confirmation, not the conftest stand-in
    horizon = FakeHorizon().install(monkeypatch)
    client.configure(multi_user=True)
    mcp = create_server(ApiKeyVerifier({"alice": hash_key(ALICE_KEY), "bob": hash_key(BOB_KEY)}))
    async with run_server_async(mcp, transport="http") as url:
        yield url, horizon


def mcp_client(url, key, prompts=None):
    async def elicit(message, response_type, params, context):
        prompts.append(message)
        return {"value": "Proceed"}

    return Client(StreamableHttpTransport(url, auth=key), elicitation_handler=elicit if prompts is not None else None)


async def call(c, tool, **args):
    return await c.call_tool(tool, args, raise_on_error=False)


def text(result) -> str:
    return " ".join(getattr(part, "text", "") for part in result.content)


def pools(result) -> list[str]:
    assert not result.is_error, text(result)
    return [p["id"] for p in result.structured_content["items"]]


async def login(c, ad_user):
    result = await call(c, "horizon_login", username=ad_user, password=f"pw-{ad_user}", domain="EXAMPLE")
    assert not result.is_error, text(result)
    assert "-secret" not in text(result)  # only 8-character hints come back


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong-key"}, {"Authorization": "Bearer"},
                                     {"Authorization": f"Basic {ALICE_KEY}"}])
async def test_requests_without_a_valid_key_are_rejected(server, headers):
    url, horizon = server
    async with httpx.AsyncClient() as http:
        resp = await http.post(url, json=_INIT, headers={**_ACCEPT, **headers})
    assert resp.status_code == 401
    assert horizon.requests == []


async def test_two_users_have_isolated_horizon_sessions(server, capsys):
    url, horizon = server
    alice_prompts: list[str] = []
    bob_prompts: list[str] = []
    async with mcp_client(url, ALICE_KEY, alice_prompts) as alice, mcp_client(url, BOB_KEY, bob_prompts) as bob:
        await login(alice, "alice")

        # Bob hasn't logged in: told to, and never served with Alice's session.
        r = await call(bob, "list_desktop_pools")
        assert r.is_error and "horizon_login" in text(r)
        assert horizon.requests == []

        assert pools(await call(alice, "list_desktop_pools")) == ["pool-of-alice"]
        await login(bob, "bob")
        assert pools(await call(bob, "list_desktop_pools")) == ["pool-of-bob"]
        alice_tok, bob_tok = horizon.tokens_sent()
        assert alice_tok.startswith("Bearer at-alice-") and bob_tok.startswith("Bearer at-bob-")

        # A destructive call asks the caller — and only the caller — to confirm.
        r = await call(alice, "delete_desktop_pool", pool_id="p1")
        assert not r.is_error, text(r)
        assert len(alice_prompts) == 1 and "Delete desktop pool" in alice_prompts[0] and bob_prompts == []
        assert horizon.requests[-1][:2] == ("DELETE", "/rest/inventory/v1/desktop-pools/p1")
        assert horizon.requests[-1][2].startswith("Bearer at-alice-")

        # Alice's token expires: only her session refreshes.
        horizon.expire("alice")
        assert pools(await call(alice, "list_desktop_pools")) == ["pool-of-alice"]
        assert [t.split("-")[1] for t in horizon.refresh_calls] == ["alice"]
        assert horizon.tokens_sent()[-1] != bob_tok
        assert pools(await call(bob, "list_desktop_pools")) == ["pool-of-bob"]
        assert horizon.tokens_sent()[-1] == bob_tok

        # Alice logs out: Bob is unaffected.
        assert not (await call(alice, "horizon_logout")).is_error
        r = await call(alice, "list_desktop_pools")
        assert r.is_error and "horizon_login" in text(r)
        assert pools(await call(bob, "list_desktop_pools")) == ["pool-of-bob"]
        assert [t.split("-")[1] for t in horizon.logouts] == ["alice"]

    _, err = capsys.readouterr()
    audit = [json.loads(line) for line in err.splitlines() if line.startswith("{")]
    assert [(e["event"], e.get("action") or e.get("outcome") or e.get("method"), e["user"]) for e in audit] == [
        ("auth", "login", "alice"),
        ("auth", "login", "bob"),
        ("confirmation", "approved", "alice"),
        ("api_request", "DELETE", "alice"),
        ("auth", "refresh", "alice"),
        ("auth", "logout", "alice"),
    ]
    for secret in (ALICE_KEY, BOB_KEY, hash_key(ALICE_KEY), hash_key(BOB_KEY), "-secret", "pw-"):
        assert secret not in err


async def test_a_session_id_cannot_be_used_with_another_users_key(server):
    url, _ = server
    async with httpx.AsyncClient() as http:
        resp = await http.post(url, json=_INIT, headers={**_ACCEPT, "Authorization": f"Bearer {ALICE_KEY}"})
        assert resp.status_code == 200
        session_id = resp.headers["mcp-session-id"]
        hijack = await http.post(
            url,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={**_ACCEPT, "Authorization": f"Bearer {BOB_KEY}", "mcp-session-id": session_id},
        )
    assert hijack.status_code == 404


async def test_sse_transport_resolves_each_users_identity_too(monkeypatch):
    from fastmcp.client.transports import SSETransport

    monkeypatch.undo()
    horizon = FakeHorizon().install(monkeypatch)
    client.configure(multi_user=True)
    mcp = create_server(ApiKeyVerifier({"alice": hash_key(ALICE_KEY), "bob": hash_key(BOB_KEY)}))
    async with run_server_async(mcp, transport="sse", path="/sse") as url:
        async with Client(SSETransport(url, auth=ALICE_KEY)) as alice, Client(SSETransport(url, auth=BOB_KEY)) as bob:
            await login(alice, "alice")
            r = await call(bob, "list_desktop_pools")
            assert r.is_error and "horizon_login" in text(r)
            await login(bob, "bob")
            assert pools(await call(alice, "list_desktop_pools")) == ["pool-of-alice"]
            assert pools(await call(bob, "list_desktop_pools")) == ["pool-of-bob"]
    assert [t.split("-")[1] for t in horizon.tokens_sent()] == ["alice", "bob"]
