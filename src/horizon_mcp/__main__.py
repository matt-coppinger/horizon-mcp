"""Entry point: python -m horizon_mcp or the `horizon-mcp` CLI command."""
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

HttpTransport = Literal["streamable-http", "sse", "http"]
_HTTP_TRANSPORTS = ("streamable-http", "sse", "http")


class StartupError(Exception):
    """The configuration is unsafe or invalid; the message says how to fix it."""


@dataclass(frozen=True)
class Mode:
    # "stdio" | "single" (MCP_API_KEY) | "unauthenticated" | "multi" (MCP_USERS_FILE)
    kind: str
    single_user: str


def _true(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() == "true"


def resolve_mode(transport: str, env: Mapping[str, str]) -> Mode:
    """Decide how the server authenticates callers and whose Horizon session they use.

    Raises StartupError for anything that would share one Horizon session between users
    by accident, or that is otherwise invalid.
    """
    from .identity import DEFAULT, LOCAL

    if transport != "stdio" and transport not in _HTTP_TRANSPORTS:
        raise StartupError(f"Unknown MCP_TRANSPORT {transport!r}: use stdio, streamable-http, sse or http.")

    users_file = env.get("MCP_USERS_FILE", "").strip()
    api_key = env.get("MCP_API_KEY", "")

    if transport == "stdio":
        if users_file:
            raise StartupError(
                "MCP_USERS_FILE only applies to HTTP transport; stdio serves a single local user. "
                "Unset it, or set MCP_TRANSPORT=streamable-http."
            )
        return Mode("stdio", LOCAL)

    if users_file and api_key:
        raise StartupError(
            "Set either MCP_API_KEY (single user) or MCP_USERS_FILE (one key per user), not both."
        )

    if users_file:
        if _true(env, "MCP_ALLOW_UNAUTHENTICATED"):
            raise StartupError("MCP_ALLOW_UNAUTHENTICATED can't be combined with MCP_USERS_FILE.")
        shared = [n for n in ("HORIZON_ACCESS_TOKEN", "HORIZON_REFRESH_TOKEN") if env.get(n)]
        if shared:
            raise StartupError(
                f"Refusing to start in multi-user mode with {' and '.join(shared)} set: that token would be "
                "shared by every user. Unset it; each user signs in with horizon_login."
            )
        if not env.get("HORIZON_BASE_URL", "").strip():
            raise StartupError(
                "Multi-user mode (MCP_USERS_FILE) requires HORIZON_BASE_URL, so every user's "
                "horizon_login goes to the same, configured Horizon server."
            )
        from .users import UsersFileError, load_users

        try:
            load_users(users_file)
        except UsersFileError as exc:
            raise StartupError(f"Refusing to start: {exc}") from None
        return Mode("multi", DEFAULT)

    if api_key:
        return Mode("single", DEFAULT)

    if _true(env, "MCP_ALLOW_UNAUTHENTICATED"):
        return Mode("unauthenticated", DEFAULT)
    raise StartupError(
        f"Refusing to start {transport} transport without MCP_API_KEY or MCP_USERS_FILE: anyone who can "
        "reach the port could call every tool with your Horizon token. Set MCP_USERS_FILE (one key per "
        "user) or MCP_API_KEY (single user), or set MCP_ALLOW_UNAUTHENTICATED=true to run without "
        "authentication (not recommended)."
    )


def configure_sessions(mode: Mode, env: Mapping[str, str]) -> None:
    from . import client

    if mode.kind == "multi":
        client.configure(multi_user=True)
    else:
        client.configure(
            multi_user=False,
            single_user=mode.single_user,
            access_token=env.get("HORIZON_ACCESS_TOKEN") or None,
            refresh_token=env.get("HORIZON_REFRESH_TOKEN") or None,
        )


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    try:
        mode = resolve_mode(transport, os.environ)
    except StartupError as exc:
        sys.exit(str(exc))
    configure_sessions(mode, os.environ)

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
