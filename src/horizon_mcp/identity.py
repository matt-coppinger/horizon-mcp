"""Who is calling: the identity every Horizon session, API call and audit line belongs to.

Three ways the server runs (chosen at startup in __main__):

  stdio                    one local user, identity "local"
  HTTP + MCP_API_KEY       one user sharing a single key, identity "default"
  HTTP + MCP_USERS_FILE    many users, each with their own key; the identity is the
                           user's name from the file

In the single-user modes every call belongs to the one fixed identity. In multi-user
mode the identity comes only from the authenticated HTTP request (the client_id the
token verifier put on FastMCP's access token); if there isn't one, the call fails —
it never falls back to a shared session.
"""
from fastmcp.server.dependencies import get_access_token

LOCAL = "local"
DEFAULT = "default"

_multi_user = False
_single_user = LOCAL


class IdentityError(PermissionError):
    """No authenticated identity for this request in multi-user mode."""


def configure(*, multi_user: bool, single_user: str = LOCAL) -> None:
    global _multi_user, _single_user
    _multi_user = multi_user
    _single_user = single_user


def is_multi_user() -> bool:
    return _multi_user


def single_user_identity() -> str:
    return _single_user


def _authenticated_name() -> str | None:
    try:
        token = get_access_token()
    except Exception:
        return None
    name = getattr(token, "client_id", None)
    return name if isinstance(name, str) and name else None


def current_identity() -> str:
    """The identity the current call acts as. Raises IdentityError in multi-user mode
    when the request carries no authenticated user."""
    if not _multi_user:
        return _single_user
    name = _authenticated_name()
    if name is None:
        raise IdentityError(
            "This request has no authenticated user, so it can't use a Horizon session. "
            "Connect with your own API key (Authorization: Bearer <key>)."
        )
    return name


def current_identity_or_none() -> str | None:
    """Like current_identity(), but None instead of raising (for audit lines)."""
    try:
        return current_identity()
    except IdentityError:
        return None
