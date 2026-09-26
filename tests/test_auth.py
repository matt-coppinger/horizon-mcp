"""Tests for auth tools: horizon_login, horizon_refresh_token, horizon_logout."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import SecretStr

from .conftest import MockFastMCP
from horizon_mcp import client
from horizon_mcp.tools import auth
from horizon_mcp.tools.auth import _resolve_base_url


@pytest.fixture
def tools(mock_mcp: MockFastMCP):
    auth.register(mock_mcp)
    return mock_mcp.tools


def make_http_client(json_data, status_code=200):
    """Return a mock async context-manager httpx.AsyncClient."""
    resp = MagicMock()
    resp.is_success = status_code < 400
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data)
    resp.text = str(json_data)

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    mock_class = MagicMock(return_value=mock_http)
    return mock_class, mock_http


# ── _resolve_base_url ────────────────────────────────────────────────────────────

def test_resolve_base_url_allows_match_with_configured():
    with patch.dict(os.environ, {"HORIZON_BASE_URL": "https://horizon.test.example.com"}):
        assert _resolve_base_url("https://horizon.test.example.com") == "https://horizon.test.example.com"


def test_resolve_base_url_allows_omitted_when_configured():
    with patch.dict(os.environ, {"HORIZON_BASE_URL": "https://horizon.test.example.com"}):
        assert _resolve_base_url("") == "https://horizon.test.example.com"


def test_resolve_base_url_allows_bootstrap_when_unconfigured():
    with patch.dict(os.environ, {"HORIZON_BASE_URL": ""}):
        assert _resolve_base_url("https://new-horizon.example.com") == "https://new-horizon.example.com"


def test_resolve_base_url_rejects_mismatch_with_configured():
    with patch.dict(os.environ, {"HORIZON_BASE_URL": "https://horizon.test.example.com"}):
        with pytest.raises(ValueError, match="does not match"):
            _resolve_base_url("https://attacker.example.com")


def test_resolve_base_url_raises_when_neither_provided():
    with patch.dict(os.environ, {"HORIZON_BASE_URL": ""}):
        with pytest.raises(ValueError, match="Provide base_url"):
            _resolve_base_url("")


# ── horizon_login ──────────────────────────────────────────────────────────────

async def test_login_sets_access_token_in_env(tools):
    mock_class, _ = make_http_client({
        "access_token": "tok-abc123",
        "refresh_token": "ref-xyz",
    })

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        await tools["horizon_login"](
            username="jsmith",
            password=SecretStr("secret"),
            domain="CORP",
            base_url="https://horizon.test.example.com",
        )

    assert os.environ.get("HORIZON_ACCESS_TOKEN") == "tok-abc123"


async def _login(tools, tokens):
    mock_class, _ = make_http_client(tokens)
    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        return await tools["horizon_login"](
            username="jsmith",
            password=SecretStr("secret"),
            domain="CORP",
            base_url="https://horizon.test.example.com",
        )


async def test_login_returns_only_hints_by_default(tools, monkeypatch):
    monkeypatch.delenv("HORIZON_EXPOSE_TOKENS", raising=False)
    result = await _login(tools, {"access_token": "tok-abc123", "refresh_token": "ref-xyz000"})

    assert result["access_token_hint"] == "tok-abc1…"
    assert result["refresh_token_hint"] == "ref-xyz0…"
    assert "access_token" not in result
    assert "refresh_token" not in result
    assert "tok-abc123" not in str(result)
    assert "ref-xyz000" not in str(result)
    assert result["status"] == "authenticated"


async def test_login_returns_full_tokens_when_exposed(tools, monkeypatch):
    monkeypatch.setenv("HORIZON_EXPOSE_TOKENS", "true")
    result = await _login(tools, {"access_token": "tok-abc123", "refresh_token": "ref-xyz000"})

    assert result["access_token"] == "tok-abc123"
    assert result["access_token_hint"] == "tok-abc1…"
    assert result["refresh_token"] == "ref-xyz000"
    assert result["refresh_token_hint"] == "ref-xyz0…"
    assert "SECURITY" in result
    assert result["status"] == "authenticated"


async def test_login_stores_refresh_token_server_side(tools):
    await _login(tools, {"access_token": "tok-abc123", "refresh_token": "ref-xyz000"})
    assert client.get_refresh_token() == "ref-xyz000"
    assert "ref-xyz000" not in os.environ.values()


async def test_login_without_refresh_token_clears_the_old_one(tools):
    client.set_refresh_token("stale-refresh")
    await _login(tools, {"access_token": "tok-abc123"})
    assert client.get_refresh_token() is None


async def test_login_sends_secret_value_not_repr(tools):
    mock_class, mock_http = make_http_client({
        "access_token": "tok", "refresh_token": "ref",
    })

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        await tools["horizon_login"](
            username="jsmith",
            password=SecretStr("my-real-password"),
            domain="CORP",
            base_url="https://horizon.test.example.com",
        )

    call_kwargs = mock_http.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert body["password"] == "my-real-password"
    assert "**" not in body["password"]


async def test_login_raises_on_non_200(tools):
    mock_class, _ = make_http_client({"error_message": "Invalid credentials"}, status_code=401)

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        with pytest.raises(ValueError, match="Login failed"):
            await tools["horizon_login"](
                username="jsmith",
                password=SecretStr("wrong"),
                domain="CORP",
                base_url="https://horizon.test.example.com",
            )


async def test_login_raises_without_base_url(tools):
    with patch.dict(os.environ, {"HORIZON_BASE_URL": ""}):
        with pytest.raises(ValueError, match="base_url"):
            await tools["horizon_login"](
                username="u", password=SecretStr("p"), domain="D",
            )


async def test_login_rejects_base_url_mismatch_without_sending_credentials(tools):
    """A base_url that differs from the configured HORIZON_BASE_URL must be rejected
    before any HTTP request is made, so credentials never reach the mismatched host."""
    mock_class, mock_http = make_http_client({"access_token": "tok", "refresh_token": "ref"})

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"), \
         patch.dict(os.environ, {"HORIZON_BASE_URL": "https://horizon.test.example.com"}):
        with pytest.raises(ValueError, match="does not match"):
            await tools["horizon_login"](
                username="jsmith",
                password=SecretStr("my-real-password"),
                domain="CORP",
                base_url="https://attacker.example.com",
            )

    mock_http.post.assert_not_called()


# ── horizon_refresh_token ──────────────────────────────────────────────────────

async def test_refresh_token_updates_env_and_returns_hint(tools, monkeypatch):
    monkeypatch.delenv("HORIZON_EXPOSE_TOKENS", raising=False)
    mock_class, _ = make_http_client({"access_token": "new-tok-999abc"})

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        result = await tools["horizon_refresh_token"](
            refresh_token=SecretStr("old-refresh"),
            base_url="https://horizon.test.example.com",
        )

    assert os.environ.get("HORIZON_ACCESS_TOKEN") == "new-tok-999abc"
    assert "access_token" not in result
    assert "new-tok-999abc" not in str(result)
    assert result["access_token_hint"] == "new-tok-…"
    assert result["status"] == "token_refreshed"
    # A refresh token passed in explicitly becomes the stored one.
    assert client.get_refresh_token() == "old-refresh"


async def test_refresh_token_returns_full_token_when_exposed(tools, monkeypatch):
    monkeypatch.setenv("HORIZON_EXPOSE_TOKENS", "true")
    mock_class, _ = make_http_client({"access_token": "new-tok-999abc"})

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        result = await tools["horizon_refresh_token"](refresh_token=SecretStr("old-refresh"))

    assert result["access_token"] == "new-tok-999abc"
    assert "SECURITY" in result


async def test_refresh_token_defaults_to_stored_token(tools):
    client.set_refresh_token("stored-refresh")
    mock_class, mock_http = make_http_client({"access_token": "new-tok-999abc"})

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        result = await tools["horizon_refresh_token"]()

    assert mock_http.post.call_args.kwargs["json"] == {"refresh_token": "stored-refresh"}
    assert result["status"] == "token_refreshed"
    assert os.environ.get("HORIZON_ACCESS_TOKEN") == "new-tok-999abc"


async def test_refresh_token_without_stored_token_asks_for_login(tools):
    mock_class, mock_http = make_http_client({"access_token": "tok"})

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class):
        with pytest.raises(ValueError, match="horizon_login"):
            await tools["horizon_refresh_token"]()

    mock_http.post.assert_not_called()


async def test_refresh_token_sends_secret_value(tools):
    mock_class, mock_http = make_http_client({"access_token": "tok"})

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        await tools["horizon_refresh_token"](
            refresh_token=SecretStr("my-refresh-token"),
            base_url="https://horizon.test.example.com",
        )

    call_kwargs = mock_http.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert body["refresh_token"] == "my-refresh-token"


async def test_refresh_token_raises_on_failure(tools):
    mock_class, _ = make_http_client({"error": "expired"}, status_code=401)

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        with pytest.raises(ValueError, match="Token refresh failed"):
            await tools["horizon_refresh_token"](
                refresh_token=SecretStr("bad"),
                base_url="https://horizon.test.example.com",
            )


async def test_refresh_token_rejects_base_url_mismatch_without_sending_token(tools):
    mock_class, mock_http = make_http_client({"access_token": "tok"})

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"), \
         patch.dict(os.environ, {"HORIZON_BASE_URL": "https://horizon.test.example.com"}):
        with pytest.raises(ValueError, match="does not match"):
            await tools["horizon_refresh_token"](
                refresh_token=SecretStr("my-refresh-token"),
                base_url="https://attacker.example.com",
            )

    mock_http.post.assert_not_called()


# ── horizon_logout ─────────────────────────────────────────────────────────────

async def test_logout_clears_access_token_env(tools):
    os.environ["HORIZON_ACCESS_TOKEN"] = "existing-token"
    mock_class, _ = make_http_client({}, status_code=200)

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        result = await tools["horizon_logout"](
            refresh_token=SecretStr("ref-tok"),
            base_url="https://horizon.test.example.com",
        )

    assert os.environ.get("HORIZON_ACCESS_TOKEN") is None
    assert result == {"logged_out": True}


async def test_logout_defaults_to_stored_token_and_forgets_it(tools):
    os.environ["HORIZON_ACCESS_TOKEN"] = "existing-token"
    client.set_refresh_token("stored-refresh")
    mock_class, mock_http = make_http_client({}, status_code=200)

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        result = await tools["horizon_logout"]()

    assert mock_http.post.call_args.kwargs["json"] == {"refresh_token": "stored-refresh"}
    assert result == {"logged_out": True}
    assert client.get_refresh_token() is None
    assert os.environ.get("HORIZON_ACCESS_TOKEN") is None


async def test_logout_without_stored_token_asks_for_login(tools):
    mock_class, mock_http = make_http_client({}, status_code=200)

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class):
        with pytest.raises(ValueError, match="horizon_login"):
            await tools["horizon_logout"]()

    mock_http.post.assert_not_called()


async def test_logout_raises_on_failure(tools):
    mock_class, _ = make_http_client({"error": "already logged out"}, status_code=400)

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        with pytest.raises(ValueError, match="Logout failed"):
            await tools["horizon_logout"](
                refresh_token=SecretStr("ref"),
                base_url="https://horizon.test.example.com",
            )


async def test_logout_rejects_base_url_mismatch_without_sending_token(tools):
    mock_class, mock_http = make_http_client({}, status_code=200)

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"), \
         patch.dict(os.environ, {"HORIZON_BASE_URL": "https://horizon.test.example.com"}):
        with pytest.raises(ValueError, match="does not match"):
            await tools["horizon_logout"](
                refresh_token=SecretStr("ref-tok"),
                base_url="https://attacker.example.com",
            )

    mock_http.post.assert_not_called()
