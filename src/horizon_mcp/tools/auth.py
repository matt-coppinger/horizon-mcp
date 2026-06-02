"""Authentication tools: login, logout, token refresh."""
import os
from typing import Annotated

import httpx
from fastmcp import FastMCP

from ..client import reset_client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def horizon_login(
        username: Annotated[str, "AD username (without domain prefix)"],
        password: Annotated[str, "AD password"],
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
        """
        url = (base_url or os.environ.get("HORIZON_BASE_URL", "")).rstrip("/")
        if not url:
            raise ValueError(
                "Provide base_url or set the HORIZON_BASE_URL environment variable."
            )
        verify = os.environ.get("HORIZON_VERIFY_SSL", "true").lower() != "false"

        async with httpx.AsyncClient(verify=verify, timeout=15.0) as http:
            resp = await http.post(
                f"{url}/rest/login",
                json={"domain": domain, "username": username, "password": password},
            )
            if not resp.is_success:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                raise ValueError(f"Login failed ({resp.status_code}): {err}")
            tokens: dict = resp.json()

        # Update running server so the new token is used immediately
        os.environ["HORIZON_ACCESS_TOKEN"] = tokens["access_token"]
        if not os.environ.get("HORIZON_BASE_URL"):
            os.environ["HORIZON_BASE_URL"] = url
        await reset_client()

        return {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token"),
            "note": (
                "Token is now active for this server session. "
                "To persist across restarts, set HORIZON_ACCESS_TOKEN in your MCP client config."
            ),
        }

    @mcp.tool()
    async def horizon_refresh_token(
        refresh_token: Annotated[str, "Refresh token obtained from horizon_login"],
        base_url: Annotated[
            str, "Horizon server URL. Defaults to HORIZON_BASE_URL env var."
        ] = "",
    ) -> dict:
        """Exchange a refresh token for a new access token.

        Use this before the current access token expires (~8 hours) to maintain
        an active session without re-entering credentials.
        """
        url = (base_url or os.environ.get("HORIZON_BASE_URL", "")).rstrip("/")
        if not url:
            raise ValueError(
                "Provide base_url or set the HORIZON_BASE_URL environment variable."
            )
        verify = os.environ.get("HORIZON_VERIFY_SSL", "true").lower() != "false"

        async with httpx.AsyncClient(verify=verify, timeout=15.0) as http:
            resp = await http.post(
                f"{url}/rest/refresh",
                json={"refresh_token": refresh_token},
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

        return {
            "access_token": result["access_token"],
            "note": "New access token is now active for this server session.",
        }

    @mcp.tool()
    async def horizon_logout(
        refresh_token: Annotated[str, "Refresh token to invalidate"],
        base_url: Annotated[
            str, "Horizon server URL. Defaults to HORIZON_BASE_URL env var."
        ] = "",
    ) -> dict:
        """Invalidate the current Horizon session (access + refresh tokens)."""
        url = (base_url or os.environ.get("HORIZON_BASE_URL", "")).rstrip("/")
        if not url:
            raise ValueError(
                "Provide base_url or set the HORIZON_BASE_URL environment variable."
            )
        token = os.environ.get("HORIZON_ACCESS_TOKEN", "")
        verify = os.environ.get("HORIZON_VERIFY_SSL", "true").lower() != "false"
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        async with httpx.AsyncClient(verify=verify, timeout=15.0) as http:
            resp = await http.post(
                f"{url}/rest/logout",
                json={"refresh_token": refresh_token},
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
