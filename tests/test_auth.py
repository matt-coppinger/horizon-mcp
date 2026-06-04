"""Tests for auth tools: horizon_login, horizon_refresh_token, horizon_logout."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import SecretStr

from .conftest import MockFastMCP
from horizon_mcp.tools import auth


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


async def test_login_returns_both_tokens(tools):
    mock_class, _ = make_http_client({
        "access_token": "tok-abc123",
        "refresh_token": "ref-xyz",
    })

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        result = await tools["horizon_login"](
            username="jsmith",
            password=SecretStr("secret"),
            domain="CORP",
            base_url="https://horizon.test.example.com",
        )

    assert result["access_token"] == "tok-abc123"
    assert result["refresh_token"] == "ref-xyz"
    assert "SECURITY" in result


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


# ── horizon_refresh_token ──────────────────────────────────────────────────────

async def test_refresh_token_updates_env(tools):
    mock_class, _ = make_http_client({"access_token": "new-tok-999"})

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        result = await tools["horizon_refresh_token"](
            refresh_token=SecretStr("old-refresh"),
            base_url="https://horizon.test.example.com",
        )

    assert os.environ.get("HORIZON_ACCESS_TOKEN") == "new-tok-999"
    assert result["access_token"] == "new-tok-999"


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


async def test_logout_raises_on_failure(tools):
    mock_class, _ = make_http_client({"error": "already logged out"}, status_code=400)

    with patch("horizon_mcp.tools.auth.httpx.AsyncClient", mock_class), \
         patch("horizon_mcp.tools.auth.reset_client"):
        with pytest.raises(ValueError, match="Logout failed"):
            await tools["horizon_logout"](
                refresh_token=SecretStr("ref"),
                base_url="https://horizon.test.example.com",
            )
