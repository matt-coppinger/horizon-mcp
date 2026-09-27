"""Per-user API keys for multi-user HTTP transport (MCP_USERS_FILE).

The users file holds only SHA-256 hashes of the keys, never the keys:

    {"users": [{"name": "alice", "key_sha256": "<64 hex chars>"}]}

Keys are issued with the `horizon-mcp-keys` command, which prints each new key once.
The server reads the file at startup; restart it after adding or removing users.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastmcp.server.auth import AccessToken, TokenVerifier

from .identity import DEFAULT, LOCAL

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
# Reserved for the single-user modes, so an audit line's "user" is never ambiguous.
RESERVED_NAMES = frozenset({LOCAL, DEFAULT})
KEY_PREFIX = "hzmcp_"


class UsersFileError(ValueError):
    """The users file is missing, unreadable or invalid."""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_key() -> str:
    # 32 random bytes = 256 bits; the prefix makes leaked keys easy to recognise and scan for.
    return KEY_PREFIX + secrets.token_urlsafe(32)


def validate_name(name: str) -> None:
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise UsersFileError(
            f"Invalid user name {name!r}: use 1-64 letters, digits, '.', '_', '@' or '-', starting with a letter or digit."
        )
    if name.lower() in RESERVED_NAMES:
        raise UsersFileError(f"User name {name!r} is reserved.")


def parse_users(data: object) -> list[dict]:
    """Validate the parsed JSON of a users file and return its user entries."""
    if not isinstance(data, dict) or not isinstance(data.get("users"), list):
        raise UsersFileError('Expected a JSON object like {"users": [{"name": ..., "key_sha256": ...}]}.')
    users: list[dict] = data["users"]
    names: set[str] = set()
    hashes: set[str] = set()
    for i, entry in enumerate(users):
        if not isinstance(entry, dict):
            raise UsersFileError(f"users[{i}] is not an object.")
        name = entry.get("name")
        validate_name(name)  # type: ignore[arg-type]
        assert isinstance(name, str)
        if name.lower() in names:
            raise UsersFileError(f"Duplicate user name {name!r}.")
        digest = entry.get("key_sha256")
        if not isinstance(digest, str) or not _HASH_PATTERN.fullmatch(digest):
            raise UsersFileError(f"User {name!r}: key_sha256 must be 64 lowercase hex characters.")
        if digest in hashes:
            raise UsersFileError(f"User {name!r}: key_sha256 is the same as another user's.")
        names.add(name.lower())
        hashes.add(digest)
    return users


def read_users_file(path: str | os.PathLike, *, missing_ok: bool = False) -> list[dict]:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        if missing_ok:
            return []
        raise UsersFileError(f"Users file {str(p)!r} does not exist.") from None
    except OSError as exc:
        raise UsersFileError(f"Can't read users file {str(p)!r}: {exc.strerror}") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise UsersFileError(f"Users file {str(p)!r} is not valid JSON: {exc}") from None
    try:
        return parse_users(data)
    except UsersFileError as exc:
        raise UsersFileError(f"Users file {str(p)!r}: {exc}") from None


def load_users(path: str | os.PathLike) -> dict[str, str]:
    """name -> key hash, for a users file that must exist and list at least one user."""
    users = read_users_file(path)
    if not users:
        raise UsersFileError(f"Users file {str(path)!r} lists no users. Add one with: horizon-mcp-keys add <name>")
    return {u["name"]: u["key_sha256"] for u in users}


def write_users_file(path: str | os.PathLike, users: list[dict]) -> None:
    """Atomically replace the users file, readable only by its owner (0600)."""
    parse_users({"users": users})
    p = Path(path)
    directory = p.parent if str(p.parent) else Path(".")
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{p.name}.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"users": users}, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.chmod(p, 0o600)


def add_user(path: str | os.PathLike, name: str) -> str:
    """Add `name` with a new random key; returns the key (the only time it exists in clear)."""
    validate_name(name)
    users = read_users_file(path, missing_ok=True)
    if any(u["name"].lower() == name.lower() for u in users):
        raise UsersFileError(f"User {name!r} already exists. Remove it first to issue a new key.")
    key = generate_key()
    users.append({
        "name": name,
        "key_sha256": hash_key(key),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    })
    write_users_file(path, users)
    return key


def remove_user(path: str | os.PathLike, name: str) -> None:
    users = read_users_file(path)
    kept = [u for u in users if u["name"].lower() != name.lower()]
    if len(kept) == len(users):
        raise UsersFileError(f"No user named {name!r}.")
    write_users_file(path, kept)


def list_users(path: str | os.PathLike) -> list[str]:
    return [u["name"] for u in read_users_file(path)]


class ApiKeyVerifier(TokenVerifier):
    """Bearer-token verifier over SHA-256 key hashes; the access token's client_id is the user name.

    The presented key is hashed and compared with every stored hash using
    hmac.compare_digest, without stopping at the first match, so the time taken
    doesn't depend on which (or whether any) entry matched.
    """

    def __init__(self, users: dict[str, str]) -> None:
        super().__init__()
        self._users = [(name, bytes.fromhex(digest)) for name, digest in users.items()]

    @classmethod
    def from_file(cls, path: str | os.PathLike) -> "ApiKeyVerifier":
        return cls(load_users(path))

    @classmethod
    def single_key(cls, key: str, name: str = DEFAULT) -> "ApiKeyVerifier":
        """Legacy single-user mode: one shared MCP_API_KEY."""
        return cls({name: hash_key(key)})

    def match(self, token: str) -> str | None:
        if not isinstance(token, str) or not token:
            return None
        try:
            presented = hashlib.sha256(token.encode("utf-8")).digest()
        except UnicodeError:
            return None
        found: str | None = None
        for name, digest in self._users:
            if hmac.compare_digest(presented, digest):
                found = name
        return found

    async def verify_token(self, token: str) -> AccessToken | None:
        name = self.match(token)
        if name is None:
            return None
        return AccessToken(token=token, client_id=name, subject=name, scopes=["mcp"], claims={"sub": name})
