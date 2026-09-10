"""Authentication tools: login, logout, token refresh."""
import os
from typing import Annotated

import httpx
from fastmcp import FastMCP
from pydantic import SecretStr

from ..client import reset_client


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


def register(mcp: FastMCP) -> None:
    @mcp.tool()
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
        """Authenticate to Horizon and return access and refresh tokens.

        The access_token is valid for ~8 hours. The refresh_token can be used with
        horizon_refresh_token to obtain a new access_token without re-entering credentials.

        This tool also updates the running server's active token so subsequent tool calls
        work immediately without restarting the server.

        SECURITY: Copy the returned access_token to your MCP client config
        (HORIZON_ACCESS_TOKEN env var), then clear it from the conversation.
        Treat both tokens as passwords — do not share or log them.
        """
        url = _resolve_base_url(base_url)
        verify = os.environ.get("HORIZON_VERIFY_SSL", "true").lower() != "false"

        async with httpx.AsyncClient(verify=verify, timeout=15.0) as http:
            resp = await http.post(
                f"{url}/rest/login",
                json={"domain": domain, "username": username, "password": password.get_secret_value()},
            )
            if not resp.is_success:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                raise ValueError(f"Login failed ({resp.status_code}): {err}")
            tokens: dict = resp.json()

        os.environ["HORIZON_ACCESS_TOKEN"] = tokens["access_token"]
        if not os.environ.get("HORIZON_BASE_URL"):
            os.environ["HORIZON_BASE_URL"] = url
        await reset_client()

        token = tokens["access_token"]
        refresh = tokens.get("refresh_token", "")
        return {
            "status": "authenticated",
            "note": "Token is now active for this server session. Set HORIZON_ACCESS_TOKEN in your MCP client config to persist it across restarts.",
            "SECURITY": "Treat these tokens as passwords. Clear them from the conversation after copying to your config. Do not commit to version control.",
            "access_token": token,
            "access_token_hint": f"{token[:8]}…",
            "refresh_token": refresh,
            "refresh_token_hint": f"{refresh[:8]}…" if refresh else "",
        }

    @mcp.tool()
    async def horizon_refresh_token(
        refresh_token: Annotated[SecretStr, "Refresh token obtained from horizon_login"],
        base_url: Annotated[
            str, "Horizon server URL. Defaults to HORIZON_BASE_URL env var."
        ] = "",
    ) -> dict:
        """Exchange a refresh token for a new access token.

        Use this before the current access token expires (~8 hours) to maintain
        an active session without re-entering credentials.
        """
        url = _resolve_base_url(base_url)
        verify = os.environ.get("HORIZON_VERIFY_SSL", "true").lower() != "false"

        async with httpx.AsyncClient(verify=verify, timeout=15.0) as http:
            resp = await http.post(
                f"{url}/rest/refresh",
                json={"refresh_token": refresh_token.get_secret_value()},
            )
            if not resp.is_success:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                raise ValueError(f"Token refresh failed ({resp.status_code}): {err}")
            result: dict = resp.json()

        os.environ["HORIZON_ACCESS_TOKEN"] = result["access_token"]
        await reset_client()

        token = result["access_token"]
        return {
            "status": "token_refreshed",
            "note": "New access token is now active for this server session. Update HORIZON_ACCESS_TOKEN in your MCP client config if you want to persist it.",
            "SECURITY": "Treat this token as a password. Clear it from the conversation after copying.",
            "access_token": token,
            "access_token_hint": f"{token[:8]}…",
        }

    @mcp.tool()
    async def horizon_logout(
        refresh_token: Annotated[SecretStr, "Refresh token to invalidate"],
        base_url: Annotated[
            str, "Horizon server URL. Defaults to HORIZON_BASE_URL env var."
        ] = "",
    ) -> dict:
        """Invalidate the current Horizon session (access + refresh tokens)."""
        url = _resolve_base_url(base_url)
        token = os.environ.get("HORIZON_ACCESS_TOKEN", "")
        verify = os.environ.get("HORIZON_VERIFY_SSL", "true").lower() != "false"
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        async with httpx.AsyncClient(verify=verify, timeout=15.0) as http:
            resp = await http.post(
                f"{url}/rest/logout",
                json={"refresh_token": refresh_token.get_secret_value()},
                headers=headers,
            )
            if not resp.is_success:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                raise ValueError(f"Logout failed ({resp.status_code}): {err}")

        os.environ.pop("HORIZON_ACCESS_TOKEN", None)
        await reset_client()
        return {"logged_out": True}
