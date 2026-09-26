"""Entry point: python -m horizon_mcp or the `horizon-mcp` CLI command."""
import os
import sys
from typing import Literal, cast

HttpTransport = Literal["streamable-http", "sse", "http"]
_HTTP_TRANSPORTS = ("streamable-http", "sse", "http")


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport != "stdio" and transport not in _HTTP_TRANSPORTS:
        sys.exit(f"Unknown MCP_TRANSPORT {transport!r}: use stdio, streamable-http, sse or http.")

    if transport != "stdio" and not os.environ.get("MCP_API_KEY"):
        if os.environ.get("MCP_ALLOW_UNAUTHENTICATED", "").lower() != "true":
            sys.exit(
                f"Refusing to start {transport} transport without MCP_API_KEY: anyone who can reach "
                "the port could call every tool with your Horizon token. Set MCP_API_KEY, or set "
                "MCP_ALLOW_UNAUTHENTICATED=true to run without authentication (not recommended)."
            )

    from .server import mcp

    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    from starlette.middleware import Middleware

    from .http_security import HostOriginGuard

    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    mcp.run(
        transport=cast(HttpTransport, transport),
        host=host,
        port=port,
        middleware=[Middleware(HostOriginGuard, bind_host=host)],
    )


if __name__ == "__main__":
    main()
