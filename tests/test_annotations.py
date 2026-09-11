"""Tests that every registered tool declares MCP annotations, and that naming
conventions (list_/get_/create_/delete_) match their declared behavior hints."""
import pytest

from .conftest import MockFastMCP
from horizon_mcp.tools import auth, config, discovery, entitlements, external, helpdesk, inventory, monitor


@pytest.fixture
def registered(mock_mcp: MockFastMCP):
    for module in (auth, config, discovery, entitlements, external, helpdesk, inventory, monitor):
        module.register(mock_mcp)
    return mock_mcp


def test_every_tool_has_annotations(registered):
    missing = [name for name, ann in registered.annotations.items() if ann is None]
    assert missing == [], f"tools registered without annotations: {missing}"


@pytest.mark.parametrize("prefix", ["list_", "get_"])
def test_list_and_get_tools_are_read_only(registered, prefix):
    matching = [name for name in registered.tools if name.startswith(prefix)]
    assert matching, f"expected at least one {prefix}* tool"
    for name in matching:
        ann = registered.annotations[name]
        assert ann.get("readOnlyHint") is True, f"{name} should have readOnlyHint=True"


def test_delete_tools_are_destructive_and_not_read_only(registered):
    matching = [name for name in registered.tools if name.startswith("delete_")]
    assert matching, "expected at least one delete_* tool"
    for name in matching:
        ann = registered.annotations[name]
        assert ann.get("readOnlyHint") is False, f"{name} should have readOnlyHint=False"
        assert ann.get("destructiveHint") is True, f"{name} should have destructiveHint=True"


def test_create_tools_are_not_read_only_and_not_destructive(registered):
    matching = [name for name in registered.tools if name.startswith("create_")]
    assert matching, "expected at least one create_* tool"
    for name in matching:
        ann = registered.annotations[name]
        assert ann.get("readOnlyHint") is False, f"{name} should have readOnlyHint=False"
        assert ann.get("destructiveHint") is False, f"{name} should have destructiveHint=False"


def test_no_tool_claims_open_world():
    # Horizon is a closed enterprise system — no tool here talks to the open web.
    from horizon_mcp.tools._annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_UPDATE, READ_ONLY
    for preset in (READ_ONLY, ADDITIVE, IDEMPOTENT_UPDATE, DESTRUCTIVE):
        assert preset["openWorldHint"] is False
