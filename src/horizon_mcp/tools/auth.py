"""Authentication tools: login, logout, token refresh."""
import os
from typing import Annotated

import httpx
from fastmcp import FastMCP
from pydantic import SecretStr

from .. import audit
from ..client import (
    get_refresh_token,
    refresh_access_token,
    reset_client,
    set_refresh_token,
    store_tokens,
    verify_ssl,
)
from ._annotations import ADDITIVE


def _resolve_base_url(base_url: str) -> str:
    """Resolve the effective Horizon server URL for an auth call.

    base_url is an MCP tool argument and therefore untrusted (it can be
    influenced by prompt injection reaching the agent that drives this
    server). Once HORIZON_BASE_URL is configured, silently honoring a
    different caller-supplied base_url would let an attacker redirect
    login/refresh/logout calls — and the credentials or tokens in their
    request bodies — to a host of their choosing. So a caller-supplied
    value is only accepted to bootstrap the server before HORIZON_BASE_URL
    is set; once it's set, base_url must match it exactly.
    """
    configured = os.environ.get("HORIZON_BASE_URL", "").rstrip("/")
    url = (base_url or configured).rstrip("/")
    if not url:
        raise ValueError("Provide base_url or set the HORIZON_BASE_URL environment variable.")
    if configured and url != configured:
        raise ValueError(
            f"base_url ({url}) does not match the configured HORIZON_BASE_URL ({configured}). "
            "Omit base_url to use the configured server, or update HORIZON_BASE_URL to change it."
        )
    return url


def _expose_tokens() -> bool:
    """HORIZON_EXPOSE_TOKENS=true returns full tokens so an operator can copy them into config.

    Off by default: anything a tool returns lands in the model's context (and the chat
    transcript), and the server refreshes tokens itself, so the model never needs them.
    """
    return os.environ.get("HORIZON_EXPOSE_TOKENS", "").strip().lower() == "true"


def _hint(token: str | None) -> str:
    return f"{token[:8]}…" if token else ""


def _stored_refresh_token(refresh_token: SecretStr | None) -> str:
    value = refresh_token.get_secret_value() if refresh_token is not None else get_refresh_token()
    if not value:
        raise ValueError("No refresh token is stored on the server. Call horizon_login to sign in.")
    return value


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=ADDITIVE)
    async def horizon_login(
        username: Annotated[str, "AD username (without domain prefix)"],
        password: Annotated[SecretStr, "AD password — masked in logs and server-side traces"],
        domain: Annotated[str, "AD domain name, e.g. CORP or corp.example.com"],
        base_url: Annotated[
            str,
            "Horizon server URL, e.g. https://horizon.corp.example.com. "
            "Defaults to HORIZON_BASE_URL env var if not provided.",
        ] = "",
    ) -> dict:
        """Authenticate to Horizon and activate the session for this server.

        The tokens are kept server-side: subsequent tool calls work immediately, and when
        the access token expires (~8 hours) the server renews it automatically with the
        refresh token. Only short token hints are returned.
        """
        url = _resolve_base_url(base_url)

        status: int | str = "error"
        try:
            async with httpx.AsyncClient(verify=verify_ssl(), timeout=15.0) as http:
                resp = await http.post(
                    f"{url}/rest/login",
                    json={"domain": domain, "username": username, "password": password.get_secret_value()},
                )
                status = resp.status_code
                if not resp.is_success:
                    try:
                        err = resp.json()
                    except Exception:
                        err = resp.text
                    raise ValueError(f"Login failed ({resp.status_code}): {err}")
                tokens: dict = resp.json()
        finally:
            audit.record("auth", action="login", status=status)

        token = tokens["access_token"]
        refresh = tokens.get("refresh_token", "")
        if not os.environ.get("HORIZON_BASE_URL"):
            os.environ["HORIZON_BASE_URL"] = url
        # A new login replaces any earlier refresh token, even with none.
        set_refresh_token(refresh)
        await store_tokens(token)

        result = {
            "status": "authenticated",
            "note": "Session is active for this server. Expired access tokens are renewed automatically "
            "using the refresh token held by the server.",
            "access_token_hint": _hint(token),
            "refresh_token_hint": _hint(refresh),
        }
        if _expose_tokens():
            result.update({
                "note": "Session is active for this server. To persist it across restarts, set "
                "HORIZON_ACCESS_TOKEN and HORIZON_REFRESH_TOKEN in your MCP client config.",
                "SECURITY": "Treat these tokens as passwords. Clear them from the conversation after copying "
                "to your config. Do not commit to version control.",
                "access_token": token,
                "refresh_token": refresh,
            })
        return result

    @mcp.tool(annotations=ADDITIVE)
    async def horizon_refresh_token(
        refresh_token: Annotated[
            SecretStr | None,
            "Refresh token to use. Omit to use the one the server stored at login (normally what you want).",
        ] = None,
        base_url: Annotated[
            str, "Horizon server URL. Defaults to HORIZON_BASE_URL env var."
        ] = "",
    ) -> dict:
        """Exchange the refresh token for a new access token.

        Rarely needed: the server already refreshes an expired access token automatically.
        """
        url = _resolve_base_url(base_url)
        refresh = _stored_refresh_token(refresh_token)

        result = await refresh_access_token(url, refresh)

        # Keep the refresh token that worked (a caller-supplied one becomes the stored one),
        # unless the server rotated it.
        set_refresh_token(refresh)
        await store_tokens(result["access_token"], result.get("refresh_token"))

        token = result["access_token"]
        out = {
            "status": "token_refreshed",
            "note": "New access token is now active for this server session.",
            "access_token_hint": _hint(token),
        }
        if _expose_tokens():
            out.update({
                "note": "New access token is now active for this server session. Update HORIZON_ACCESS_TOKEN "
                "in your MCP client config if you want to persist it.",
                "SECURITY": "Treat this token as a password. Clear it from the conversation after copying.",
                "access_token": token,
            })
        return out

    @mcp.tool(annotations=ADDITIVE)
    async def horizon_logout(
        refresh_token: Annotated[
            SecretStr | None,
            "Refresh token to invalidate. Omit to use the one the server stored at login.",
        ] = None,
        base_url: Annotated[
            str, "Horizon server URL. Defaults to HORIZON_BASE_URL env var."
        ] = "",
    ) -> dict:
        """Invalidate the current Horizon session (access + refresh tokens)."""
        url = _resolve_base_url(base_url)
        refresh = _stored_refresh_token(refresh_token)
        token = os.environ.get("HORIZON_ACCESS_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        status: int | str = "error"
        try:
            async with httpx.AsyncClient(verify=verify_ssl(), timeout=15.0) as http:
                resp = await http.post(
                    f"{url}/rest/logout",
                    json={"refresh_token": refresh},
                    headers=headers,
                )
                status = resp.status_code
                if not resp.is_success:
                    try:
                        err = resp.json()
                    except Exception:
                        err = resp.text
                    raise ValueError(f"Logout failed ({resp.status_code}): {err}")
        finally:
            audit.record("auth", action="logout", status=status)

        os.environ.pop("HORIZON_ACCESS_TOKEN", None)
        set_refresh_token(None)
        await reset_client()
        return {"logged_out": True}
