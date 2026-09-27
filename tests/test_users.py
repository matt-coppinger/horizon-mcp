"""Per-user API keys: the users file, the horizon-mcp-keys CLI and the bearer-token verifier."""
import hashlib
import json
import os
import stat

import pytest

from horizon_mcp import keys, users
from horizon_mcp.users import ApiKeyVerifier, UsersFileError, hash_key, load_users, parse_users

H1, H2 = "a" * 64, "b" * 64


def run_cli(capsys, *argv):
    code = keys.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_add_prints_key_once_and_stores_only_its_hash(tmp_path, capsys):
    f = tmp_path / "users.json"
    code, out, err = run_cli(capsys, "add", "alice", "--file", str(f))
    assert code == 0
    key = out.strip()
    assert key.startswith("hzmcp_") and len(key) >= 40
    assert "shown only once" in err and "securely" in err
    assert key not in err  # stdout carries the key, stderr the warning

    text = f.read_text()
    assert key not in text
    [entry] = json.loads(text)["users"]
    assert entry["name"] == "alice"
    assert entry["key_sha256"] == hashlib.sha256(key.encode()).hexdigest()


def test_users_file_is_owner_only(tmp_path, capsys):
    f = tmp_path / "users.json"
    run_cli(capsys, "add", "alice", "--file", str(f))
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    run_cli(capsys, "add", "bob", "--file", str(f))
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    assert not [p for p in tmp_path.iterdir() if p.name != "users.json"]  # no temp files left


async def test_printed_key_verifies_as_that_user(tmp_path, capsys):
    f = tmp_path / "users.json"
    _, alice_key, _ = run_cli(capsys, "add", "alice", "--file", str(f))
    _, bob_key, _ = run_cli(capsys, "add", "bob", "--file", str(f))
    verifier = ApiKeyVerifier.from_file(f)
    a = await verifier.verify_token(alice_key.strip())
    b = await verifier.verify_token(bob_key.strip())
    assert a is not None and a.client_id == "alice"
    assert b is not None and b.client_id == "bob"


def test_duplicate_names_are_rejected(tmp_path, capsys):
    f = tmp_path / "users.json"
    run_cli(capsys, "add", "alice", "--file", str(f))
    before = f.read_text()
    code, out, err = run_cli(capsys, "add", "Alice", "--file", str(f))
    assert code == 1 and "already exists" in err and out == ""
    assert f.read_text() == before


def test_list_shows_names_only(tmp_path, capsys):
    f = tmp_path / "users.json"
    run_cli(capsys, "add", "alice", "--file", str(f))
    run_cli(capsys, "add", "bob", "--file", str(f))
    code, out, _ = run_cli(capsys, "list", "--file", str(f))
    assert code == 0 and out.split() == ["alice", "bob"]


def test_remove_revokes_the_key(tmp_path, capsys):
    f = tmp_path / "users.json"
    run_cli(capsys, "add", "alice", "--file", str(f))
    run_cli(capsys, "add", "bob", "--file", str(f))
    assert run_cli(capsys, "remove", "alice", "--file", str(f))[0] == 0
    assert list(load_users(f)) == ["bob"]
    code, _, err = run_cli(capsys, "remove", "alice", "--file", str(f))
    assert code == 1 and "No user named" in err


def test_file_defaults_to_mcp_users_file(tmp_path, capsys, monkeypatch):
    f = tmp_path / "users.json"
    monkeypatch.setenv("MCP_USERS_FILE", str(f))
    assert run_cli(capsys, "add", "alice")[0] == 0
    assert list(load_users(f)) == ["alice"]


def test_no_file_is_an_error(capsys, monkeypatch):
    monkeypatch.delenv("MCP_USERS_FILE", raising=False)
    code, _, err = run_cli(capsys, "list")
    assert code == 2 and "MCP_USERS_FILE" in err


@pytest.mark.parametrize("name", ["", "-alice", "a b", "a/b", "x" * 65, "local", "DEFAULT", "al\nice", "alice\n"])
def test_invalid_or_reserved_names_are_rejected(tmp_path, capsys, name):
    code, _, err = run_cli(capsys, "add", "--file", str(tmp_path / "users.json"), "--", name)
    assert code == 1 and ("Invalid user name" in err or "reserved" in err)


# ── users file validation ───────────────────────────────────────────────────

@pytest.mark.parametrize("data,match", [
    ([], "Expected a JSON object"),
    ({"users": {}}, "Expected a JSON object"),
    ({"users": ["alice"]}, "not an object"),
    ({"users": [{"name": "alice"}]}, "key_sha256"),
    ({"users": [{"name": "alice", "key_sha256": "A" * 64}]}, "key_sha256"),
    ({"users": [{"name": "alice", "key_sha256": "a" * 63}]}, "key_sha256"),
    ({"users": [{"name": "alice", "key_sha256": H1}, {"name": "ALICE", "key_sha256": H2}]}, "Duplicate"),
    ({"users": [{"name": "alice", "key_sha256": H1}, {"name": "bob", "key_sha256": H1}]}, "same as another"),
    ({"users": [{"name": "../x", "key_sha256": H1}]}, "Invalid user name"),
    ({"users": [{"name": 7, "key_sha256": H1}]}, "Invalid user name"),
])
def test_invalid_users_data_is_rejected(data, match):
    with pytest.raises(UsersFileError, match=match):
        parse_users(data)


def test_load_users_rejects_missing_bad_json_and_empty(tmp_path):
    with pytest.raises(UsersFileError, match="does not exist"):
        load_users(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(UsersFileError, match="not valid JSON"):
        load_users(bad)
    empty = tmp_path / "empty.json"
    empty.write_text('{"users": []}')
    with pytest.raises(UsersFileError, match="no users"):
        load_users(empty)


# ── verifier ──────────────────────────────────────────────────────────────────

@pytest.fixture
def verifier():
    return ApiKeyVerifier({"alice": hash_key("alice-key"), "bob": hash_key("bob-key")})


async def test_valid_keys_map_to_their_identity(verifier):
    a = await verifier.verify_token("alice-key")
    b = await verifier.verify_token("bob-key")
    assert a is not None and (a.client_id, a.subject) == ("alice", "alice")
    assert b is not None and b.client_id == "bob"


@pytest.mark.parametrize("token", ["", "alice-key ", "ALICE-KEY", "alice", hash_key("alice-key"), "\udcff", "x" * 10000])
async def test_wrong_empty_or_garbage_keys_are_rejected(verifier, token):
    assert await verifier.verify_token(token) is None


async def test_single_key_mode_identity_is_default():
    v = ApiKeyVerifier.single_key("shared-key")
    t = await v.verify_token("shared-key")
    assert t is not None and t.client_id == "default"
    assert await v.verify_token("other") is None


async def test_verifier_compares_every_hash_with_compare_digest(verifier, monkeypatch):
    calls = []
    real = users.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(users.hmac, "compare_digest", spy)
    assert (await verifier.verify_token("alice-key")).client_id == "alice"  # type: ignore[union-attr]
    assert len(calls) == 2  # doesn't stop at the first (matching) entry
    calls.clear()
    assert await verifier.verify_token("nobody") is None
    assert len(calls) == 2
