"""Horizon REST API HTTP client."""
import asyncio
import os
from typing import Any
from urllib.parse import quote, unquote

import httpx

from . import audit

_client: httpx.AsyncClient | None = None
# Module-level lock is safe in Python 3.10+ (no longer bound to a loop at construction).
_lock = asyncio.Lock()
# Separate from _lock: a refresh calls reset_client(), which takes _lock itself.
_refresh_lock = asyncio.Lock()

# The refresh token stays in this process: it isn't returned to the model (unless
# HORIZON_EXPOSE_TOKENS=true) or put in os.environ, so subprocesses don't inherit it.
_refresh_token: str | None = os.environ.get("HORIZON_REFRESH_TOKEN") or None

_MUTATING = ("POST", "PUT", "DELETE")
_RELOGIN = "Call horizon_login to sign in again."


class TokenRefreshError(ValueError):
    """The Horizon /rest/refresh call failed. status_code is None for transport errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def verify_ssl() -> bool:
    return os.environ.get("HORIZON_VERIFY_SSL", "true").lower() != "false"


def get_refresh_token() -> str | None:
    return _refresh_token


def set_refresh_token(token: str | None) -> None:
    global _refresh_token
    _refresh_token = token or None


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
        verify = verify_ssl()
        _client = httpx.AsyncClient(
            base_url=f"{base_url}/rest",
            headers={"Authorization": f"Bearer {token}"},
            # verify must be passed to the transport itself, not just the client —
            # AsyncClient's own verify= is silently ignored whenever an explicit
            # transport= is supplied, since the transport already has its own
            # (default True) verify setting baked in by the time the client sees it.
            transport=httpx.AsyncHTTPTransport(retries=3, verify=verify),
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def reset_client() -> None:
    """Close and reset the shared client (call after token rotation)."""
    global _client
    async with _lock:
        if _client is not None and not _client.is_closed:
            await _client.aclose()
        _client = None


def _reject_traversal(path: str) -> None:
    """Reject request paths containing dot-segments.

    Tool wrappers build paths by interpolating caller-supplied IDs
    (e.g. pool_id, farm_id) directly into an f-string. httpx resolves
    "." and ".." dot-segments per RFC 3986 before dispatching the
    request, so an ID containing "../" can redirect the request to a
    completely different REST endpoint than the tool intends. Checking
    every path here — the single choke point all api_* calls pass
    through — catches this regardless of which tool built the path.
    """
    decoded = unquote(path)
    if any(segment in (".", "..") for segment in decoded.split("/")):
        raise ValueError(f"Invalid request path (contains a dot-segment): {path!r}")
    # Paths are built from literals plus seg()-encoded IDs, so none of these
    # should ever appear raw — they'd add a query string, cut off the rest of
    # the path, or be treated as a separator by some servers.
    if any(ch in path for ch in "?#\\"):
        raise ValueError(f"Invalid request path (contains ?, # or \\): {path!r}")


def seg(value: str) -> str:
    """Percent-encode a caller-supplied ID for use as a single URL path segment.

    Every character outside [A-Za-z0-9_.~-] is encoded, so an ID can never add
    path segments, a query string or a fragment. Real Horizon IDs (UUIDs,
    SIDs like S-1-5-32-544, vCenter refs like vm-2001) pass through unchanged.
    """
    value = str(value)
    if not value or value in (".", ".."):
        raise ValueError(f"Invalid ID: {value!r}")
    return quote(value, safe="")


def _parse_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        detail = body.get("errors") or body.get("error_message") or body.get("message")
        return str(detail) if detail else str(body)
    except Exception:
        return resp.text or f"HTTP {resp.status_code}"


async def refresh_access_token(base_url: str, refresh_token: str, *, trigger: str = "tool") -> dict:
    """POST {base_url}/rest/refresh and return the response body ({"access_token": ...}).

    Shared by horizon_refresh_token and the automatic refresh on 401. Stores nothing —
    the caller decides what to do with the result. Raises TokenRefreshError on failure.
    """
    status: int | str = "error"
    try:
        async with httpx.AsyncClient(verify=verify_ssl(), timeout=15.0) as http:
            try:
                resp = await http.post(f"{base_url}/rest/refresh", json={"refresh_token": refresh_token})
            except httpx.HTTPError as exc:
                raise TokenRefreshError(f"Token refresh failed: {type(exc).__name__}") from None
            status = resp.status_code
            if not resp.is_success:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                raise TokenRefreshError(f"Token refresh failed ({resp.status_code}): {err}", resp.status_code)
            return resp.json()
    finally:
        audit.record("auth", action="refresh", trigger=trigger, status=status)


async def store_tokens(access_token: str, refresh_token: str | None = None) -> None:
    """Make access_token the active token (and keep refresh_token, if one is given)."""
    os.environ["HORIZON_ACCESS_TOKEN"] = access_token
    if refresh_token:
        set_refresh_token(refresh_token)
    await reset_client()


async def _refresh_session(stale_token: str) -> None:
    """Replace stale_token with a new access token — once, however many requests got a 401.

    Requests queued on the lock find the token already replaced and just retry with it.
    """
    async with _refresh_lock:
        if os.environ.get("HORIZON_ACCESS_TOKEN", "") != stale_token:
            return
        if not _refresh_token:
            raise ValueError(
                "The Horizon access token is missing, expired or was rejected (HTTP 401), and there's "
                f"no refresh token to renew it automatically. {_RELOGIN}"
            )
        base_url = os.environ.get("HORIZON_BASE_URL", "").rstrip("/")
        try:
            result = await refresh_access_token(base_url, _refresh_token, trigger="auto")
        except TokenRefreshError as exc:
            # A refresh token the server rejected won't start working again: drop it so
            # later calls fail fast instead of each retrying it. Keep it on network errors.
            if exc.status_code is not None and 400 <= exc.status_code < 500:
                set_refresh_token(None)
            raise ValueError(
                f"The Horizon access token has expired and couldn't be refreshed automatically ({exc}). {_RELOGIN}"
            ) from None
        await store_tokens(result["access_token"], result.get("refresh_token"))


async def _send(method: str, path: str, **kwargs: Any) -> Any:
    """Send one request; on a 401, refresh the token and retry exactly once."""
    _reject_traversal(path)
    retried = False
    try:
        if not os.environ.get("HORIZON_ACCESS_TOKEN") and _refresh_token:
            # Started with only HORIZON_REFRESH_TOKEN (or after a failed login) — get an access token first.
            await _refresh_session("")
        client = await get_client()
        token = os.environ.get("HORIZON_ACCESS_TOKEN", "")
        resp = await client.request(method, path, **kwargs)
        if resp.status_code == 401:
            await _refresh_session(token)
            retried = True
            client = await get_client()
            resp = await client.request(method, path, **kwargs)
    except Exception as exc:
        # Log the exception type only — messages from lower layers aren't guaranteed secret-free.
        if method in _MUTATING:
            audit.record("api_request", method=method, path=path, error=type(exc).__name__, retried=retried)
        raise
    if method in _MUTATING:
        audit.record("api_request", method=method, path=path, status=resp.status_code, retried=retried)
    if not resp.is_success:
        hint = f" Still rejected after refreshing the token. {_RELOGIN}" if retried and resp.status_code == 401 else ""
        raise ValueError(f"{method} {path} failed ({resp.status_code}): {_parse_error(resp)}{hint}")
    return resp.json() if resp.content else None


def _clean(params: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (params or {}).items() if v is not None}


async def api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    return await _send("GET", path, params=_clean(params))


async def api_post(path: str, body: Any = None, params: dict[str, Any] | None = None) -> Any:
    return await _send("POST", path, json=body, params=_clean(params))


async def api_put(path: str, body: Any = None) -> Any:
    return await _send("PUT", path, json=body)


async def api_delete(path: str, body: Any = None) -> Any:
    return await _send("DELETE", path, json=body)
