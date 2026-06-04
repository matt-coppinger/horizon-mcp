"""Tests for client.py: _parse_error, get_client env validation, reset_client."""
import os
import pytest
from unittest.mock import MagicMock, patch

import httpx

from horizon_mcp.client import _parse_error, get_client, reset_client


@pytest.fixture(autouse=True)
async def clean_client():
    await reset_client()
    yield
    await reset_client()


def make_response(json_data=None, text="", status_code=400):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("not json"))
    return resp


# ── _parse_error ───────────────────────────────────────────────────────────────

def test_parse_error_uses_errors_field():
    resp = make_response(json_data={"errors": "session not found"})
    assert _parse_error(resp) == "session not found"


def test_parse_error_errors_list_is_stringified():
    resp = make_response(json_data={"errors": ["err1", "err2"]})
    result = _parse_error(resp)
    assert isinstance(result, str)
    assert "err1" in result


def test_parse_error_uses_error_message_field():
    resp = make_response(json_data={"error_message": "bad token"})
    assert _parse_error(resp) == "bad token"


def test_parse_error_uses_message_field():
    resp = make_response(json_data={"message": "resource not found"})
    assert _parse_error(resp) == "resource not found"


def test_parse_error_falls_back_to_full_body():
    resp = make_response(json_data={"code": 404, "unknown_field": "data"})
    result = _parse_error(resp)
    assert isinstance(result, str)
    assert len(result) > 0


def test_parse_error_non_json_uses_text():
    resp = make_response(text="Service Unavailable")
    assert _parse_error(resp) == "Service Unavailable"


def test_parse_error_empty_text_uses_status_code():
    resp = make_response(text="", status_code=503)
    result = _parse_error(resp)
    assert "503" in result


# ── get_client ─────────────────────────────────────────────────────────────────

async def test_get_client_raises_without_base_url():
    with patch.dict(os.environ, {"HORIZON_BASE_URL": "", "HORIZON_ACCESS_TOKEN": "tok"}):
        with pytest.raises(ValueError, match="HORIZON_BASE_URL"):
            await get_client()


async def test_get_client_raises_without_token():
    with patch.dict(os.environ, {"HORIZON_BASE_URL": "https://h.test", "HORIZON_ACCESS_TOKEN": ""}):
        with pytest.raises(ValueError, match="HORIZON_ACCESS_TOKEN"):
            await get_client()


async def test_get_client_returns_same_instance_on_repeated_calls():
    with patch.dict(os.environ, {
        "HORIZON_BASE_URL": "https://horizon.test.example.com",
        "HORIZON_ACCESS_TOKEN": "test-token",
        "HORIZON_VERIFY_SSL": "false",
    }):
        client1 = await get_client()
        client2 = await get_client()
    assert client1 is client2


# ── reset_client ───────────────────────────────────────────────────────────────

async def test_reset_client_idempotent():
    await reset_client()
    await reset_client()  # should not raise


async def test_reset_client_forces_new_instance():
    with patch.dict(os.environ, {
        "HORIZON_BASE_URL": "https://horizon.test.example.com",
        "HORIZON_ACCESS_TOKEN": "test-token",
        "HORIZON_VERIFY_SSL": "false",
    }):
        client1 = await get_client()
        await reset_client()
        client2 = await get_client()
    assert client1 is not client2
