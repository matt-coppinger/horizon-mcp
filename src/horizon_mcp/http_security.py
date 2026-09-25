"""Host/Origin header validation for the HTTP transports (DNS-rebinding protection).

FastMCP doesn't enable the MCP SDK's DNS-rebinding protection by default, so a
server bound to localhost can be reached by any web page whose domain is
re-pointed at 127.0.0.1. This middleware rejects requests whose Host header
isn't an expected name, and browser requests from origins that aren't allowed.
"""
import os
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _split_env(name: str) -> set[str]:
    return {v.strip().lower() for v in os.environ.get(name, "").split(",") if v.strip()}


def _hostname(value: str) -> str:
    """Host header or origin authority -> bare lowercase hostname (no port, no brackets)."""
    return (urlsplit(f"//{value}").hostname or "").lower()


class HostOriginGuard:
    def __init__(self, app: ASGIApp, bind_host: str) -> None:
        self.app = app
        # Host names this server answers to. Unset + non-loopback bind (e.g. 0.0.0.0
        # in Docker) means clients may use any name, so Host isn't checked; the
        # API key is the control there.
        self.allowed_hosts = {_hostname(h) for h in _split_env("MCP_ALLOWED_HOSTS")}
        if not self.allowed_hosts and bind_host.lower() in LOOPBACK_HOSTS:
            self.allowed_hosts = set(LOOPBACK_HOSTS)
        # Browser origins allowed to call the server. Non-browser MCP clients send no
        # Origin header and are unaffected. Loopback origins (e.g. MCP Inspector) are
        # allowed by default only when the server itself is bound to loopback.
        self.allowed_origins = _split_env("MCP_ALLOWED_ORIGINS")
        self.allow_loopback_origins = bind_host.lower() in LOOPBACK_HOSTS

    def _origin_ok(self, origin: str) -> bool:
        if origin.lower() in self.allowed_origins:
            return True
        parts = urlsplit(origin)
        return self.allow_loopback_origins and parts.scheme in ("http", "https") and (
            (parts.hostname or "").lower() in LOOPBACK_HOSTS
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            if self.allowed_hosts and _hostname(headers.get("host", "")) not in self.allowed_hosts:
                await PlainTextResponse("Invalid Host header", status_code=421)(scope, receive, send)
                return
            origin = headers.get("origin")
            if origin and not self._origin_ok(origin):
                await PlainTextResponse("Origin not allowed", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
