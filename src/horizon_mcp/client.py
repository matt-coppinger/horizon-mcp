"""Horizon REST API HTTP client."""
import asyncio
import os
from typing import Any

import httpx

_client: httpx.AsyncClient | None = None
# Module-level lock is safe in Python 3.10+ (no longer bound to a loop at construction).
_lock = asyncio.Lock()


async def get_client() -> httpx.AsyncClient:
    """Return the shared httpx client, creating it on first call."""
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    async with _lock:
        if _client is not None and not _client.is_closed:
            return _client
        base_url = os.environ.get("HORIZON_BASE_URL", "").rstrip("/")
        if not base_url:
            raise ValueError(
                "HORIZON_BASE_URL is not set. "
                "Configure it in your MCP client settings, e.g. https://horizon.example.com"
            )
        token = os.environ.get("HORIZON_ACCESS_TOKEN", "")
        if not token:
            raise ValueError(
                "HORIZON_ACCESS_TOKEN is not set. "
                "Call horizon_login to authenticate and get an access token."
            )
        verify = os.environ.get("HORIZON_VERIFY_SSL", "true").lower() != "false"
        _client = httpx.AsyncClient(
            base_url=f"{base_url}/rest",
            headers={"Authorization": f"Bearer {token}"},
            verify=verify,
            transport=httpx.AsyncHTTPTransport(retries=3),
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def reset_client() -> None:
    """Close and reset the shared client (call after token rotation)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _parse_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        detail = body.get("errors") or body.get("error_message") or body.get("message")
        return str(detail) if detail else str(body)
    except Exception:
        return resp.text or f"HTTP {resp.status_code}"


async def api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    client = await get_client()
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    resp = await client.get(path, params=clean)
    if not resp.is_success:
        raise ValueError(f"GET {path} failed ({resp.status_code}): {_parse_error(resp)}")
    return resp.json() if resp.content else None


async def api_post(path: str, body: Any = None, params: dict[str, Any] | None = None) -> Any:
    client = await get_client()
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    resp = await client.post(path, json=body, params=clean)
    if not resp.is_success:
        raise ValueError(f"POST {path} failed ({resp.status_code}): {_parse_error(resp)}")
    return resp.json() if resp.content else None


async def api_put(path: str, body: Any = None) -> Any:
    client = await get_client()
    resp = await client.put(path, json=body)
    if not resp.is_success:
        raise ValueError(f"PUT {path} failed ({resp.status_code}): {_parse_error(resp)}")
    return resp.json() if resp.content else None


async def api_delete(path: str, body: Any = None) -> Any:
    client = await get_client()
    resp = await client.request("DELETE", path, json=body)
    if not resp.is_success:
        raise ValueError(f"DELETE {path} failed ({resp.status_code}): {_parse_error(resp)}")
    return resp.json() if resp.content else None
