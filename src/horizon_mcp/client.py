"""Horizon REST API HTTP client, with one isolated Horizon session per identity.

Every Horizon call resolves the calling identity (identity.current_identity()) and uses
only that identity's session: its access token, refresh token, httpx client and refresh
lock. No code path reads another identity's token, and os.environ is not the live
token store (HORIZON_ACCESS_TOKEN / HORIZON_REFRESH_TOKEN only seed the single-user
session at startup).
"""
import asyncio
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote

import httpx

from . import audit, identity

_MUTATING = ("POST", "PUT", "DELETE")
_RELOGIN = "Call horizon_login to sign in again."


class TokenRefreshError(ValueError):
    """The Horizon /rest/refresh call failed. status_code is None for transport errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def verify_ssl() -> bool:
    return os.environ.get("HORIZON_VERIFY_SSL", "true").lower() != "false"


def new_transport(retries: int = 0) -> httpx.AsyncBaseTransport:
    """The transport for every request to Horizon (API calls and login/refresh/logout).

    verify must be passed to the transport itself, not just the client —
    AsyncClient's own verify= is silently ignored whenever an explicit
    transport= is supplied, since the transport already has its own
    (default True) verify setting baked in by the time the client sees it.
    """
    return httpx.AsyncHTTPTransport(retries=retries, verify=verify_ssl())


def base_url() -> str:
    return os.environ.get("HORIZON_BASE_URL", "").rstrip("/")


@dataclass(eq=False)
class HorizonSession:
    """One identity's Horizon session. Nothing in it is shared with another identity.

    The tokens stay in this process: they aren't returned to the model (unless
    HORIZON_EXPOSE_TOKENS=true) or put in os.environ, so subprocesses don't inherit them.
    """

    identity: str
    access_token: str | None = None
    refresh_token: str | None = None
    client: httpx.AsyncClient | None = None
    # Separate from lock: a refresh can end up closing the client, which takes lock.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __repr__(self) -> str:  # never show tokens in reprs, tracebacks or logs
        return f"HorizonSession(identity={self.identity!r}, logged_in={bool(self.access_token)})"


# identity -> session. Only identities the server authenticated (or the single-user
# identity) get an entry, so the store is bounded by the number of configured users.
_sessions: dict[str, HorizonSession] = {}


def configure(
    *,
    multi_user: bool,
    single_user: str = identity.LOCAL,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> None:
    """Set the identity mode and start with no sessions (called at startup).

    In the single-user modes the tokens (normally HORIZON_ACCESS_TOKEN /
    HORIZON_REFRESH_TOKEN from the environment) seed that user's session. Multi-user
    mode never seeds a session: every user logs in with their own account.
    """
    if multi_user and (access_token or refresh_token):
        raise ValueError("Multi-user mode can't start with a shared Horizon token.")
    identity.configure(multi_user=multi_user, single_user=single_user)
    _sessions.clear()
    if not multi_user and (access_token or refresh_token):
        _sessions[single_user] = HorizonSession(
            single_user, access_token=access_token or None, refresh_token=refresh_token or None
        )


def current_session() -> HorizonSession:
    """The calling identity's session.

    Raises identity.IdentityError in multi-user mode when the request isn't authenticated.
    In multi-user mode a user who isn't signed in gets an empty session that is only kept
    once it holds tokens (store_tokens), so the store only grows with signed-in users.
    """
    name = identity.current_identity()
    session = _sessions.get(name)
    if session is None:
        session = HorizonSession(name)
        if not identity.is_multi_user():
            _sessions[name] = session
    return session


def get_refresh_token() -> str | None:
    return current_session().refresh_token


def set_refresh_token(token: str | None) -> None:
    current_session().refresh_token = token or None


async def get_client(session: HorizonSession | None = None) -> httpx.AsyncClient:
    """Return the session's httpx client, creating it on first call.

    The client carries no credentials: _send adds the session's own token to each request.
    """
    s = session or current_session()
    if not s.access_token:
        raise ValueError(
            "You're not signed in to Horizon (no access token for this user). "
            "Call horizon_login to authenticate."
        )
    if s.client is not None and not s.client.is_closed:
        return s.client
    async with s.lock:
        if s.client is not None and not s.client.is_closed:
            return s.client
        url = base_url()
        if not url:
            raise ValueError(
                "HORIZON_BASE_URL is not set. "
                "Configure it in your MCP client settings, e.g. https://horizon.example.com"
            )
        s.client = httpx.AsyncClient(
            base_url=f"{url}/rest",
            transport=new_transport(retries=3),
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return s.client


async def _close_client(s: HorizonSession) -> None:
    async with s.lock:
        if s.client is not None and not s.client.is_closed:
            await s.client.aclose()
        s.client = None


async def reset_client(session: HorizonSession | None = None) -> None:
    """Close and reset the calling identity's client."""
    await _close_client(session or current_session())


async def end_session(session: HorizonSession | None = None) -> None:
    """Forget an identity's tokens and close its client (logout, or a dead refresh token)."""
    s = session or current_session()
    s.access_token = None
    s.refresh_token = None
    await _close_client(s)
    if _sessions.get(s.identity) is s:
        del _sessions[s.identity]


async def close_all() -> None:
    """Close every session's client and forget all sessions (shutdown, tests)."""
    for s in list(_sessions.values()):
        await _close_client(s)
    _sessions.clear()


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
        async with httpx.AsyncClient(transport=new_transport(), timeout=15.0) as http:
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


async def store_tokens(
    access_token: str, refresh_token: str | None = None, *, session: HorizonSession | None = None
) -> None:
    """Make access_token the session's active token (and keep refresh_token, if one is given).

    The client needn't be rebuilt: _send reads the session's token for every request.
    """
    s = session or current_session()
    s.access_token = access_token
    if refresh_token:
        s.refresh_token = refresh_token
    _sessions[s.identity] = s


async def _refresh_session(s: HorizonSession, stale_token: str) -> None:
    """Replace the session's stale_token with a new access token — once, however many of
    its requests got a 401. Other identities have their own lock and never wait on this one.

    Requests queued on the lock find the token already replaced and just retry with it.
    """
    async with s.refresh_lock:
        if (s.access_token or "") != stale_token:
            return
        if not s.refresh_token:
            raise ValueError(
                "The Horizon access token is missing, expired or was rejected (HTTP 401), and there's "
                f"no refresh token to renew it automatically. {_RELOGIN}"
            )
        used = s.refresh_token
        try:
            result = await refresh_access_token(base_url(), used, trigger="auto")
        except TokenRefreshError as exc:
            # A refresh token the server rejected won't start working again: drop it so
            # later calls fail fast instead of each retrying it. Keep it on network errors.
            # (Unless the user logged in again meanwhile — then keep the new session.)
            if exc.status_code is not None and 400 <= exc.status_code < 500 and s.refresh_token == used:
                s.refresh_token = None
                if identity.is_multi_user() and (s.access_token or "") == stale_token:
                    # Nothing usable is left: free the session (the user logs in again).
                    await end_session(s)
            raise ValueError(
                f"The Horizon access token has expired and couldn't be refreshed automatically ({exc}). {_RELOGIN}"
            ) from None
        if (s.access_token or "") == stale_token:  # not replaced by a new login meanwhile
            await store_tokens(result["access_token"], result.get("refresh_token"), session=s)


def _auth_header(s: HorizonSession) -> dict[str, str]:
    return {"Authorization": f"Bearer {s.access_token or ''}"}


async def _send(method: str, path: str, **kwargs: Any) -> Any:
    """Send one request as the calling identity; on a 401, refresh its token and retry exactly once."""
    _reject_traversal(path)
    retried = False
    try:
        # Resolved once, so a call can never switch identities part-way through.
        s = current_session()
        if not s.access_token and s.refresh_token:
            # Started with only HORIZON_REFRESH_TOKEN (or after a failed login) — get an access token first.
            await _refresh_session(s, "")
        client = await get_client(s)
        token = s.access_token or ""
        resp = await client.request(method, path, headers=_auth_header(s), **kwargs)
        if resp.status_code == 401:
            await _refresh_session(s, token)
            retried = True
            client = await get_client(s)
            resp = await client.request(method, path, headers=_auth_header(s), **kwargs)
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


# Import-time default: one local user, seeded from the environment. __main__
# reconfigures this for the transport and auth mode it starts with.
configure(
    multi_user=False,
    access_token=os.environ.get("HORIZON_ACCESS_TOKEN") or None,
    refresh_token=os.environ.get("HORIZON_REFRESH_TOKEN") or None,
)
