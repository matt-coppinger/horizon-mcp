"""Tests for external tools: list_network_interface_cards."""
import pytest
from unittest.mock import patch

from .conftest import MockFastMCP
from horizon_mcp.tools import external


@pytest.fixture
def tools(mock_mcp: MockFastMCP):
    external.register(mock_mcp)
    return mock_mcp.tools


# ── list_network_interface_cards ──────────────────────────────────────────────

async def test_list_nics_requires_base_vm_or_template(tools):
    with patch("horizon_mcp.tools.external.api_get") as mock_get:
        with pytest.raises(ValueError, match="base_vm_id .* or vm_template_id"):
            await tools["list_network_interface_cards"](vcenter_id="vc1")
    mock_get.assert_not_called()


@pytest.mark.parametrize("kwargs,expected_params", [
    ({"base_vm_id": "vm1"}, {"vcenter_id": "vc1", "base_vm_id": "vm1"}),
    ({"base_vm_id": "vm1", "base_snapshot_id": "snap1"},
     {"vcenter_id": "vc1", "base_vm_id": "vm1", "base_snapshot_id": "snap1"}),
    ({"vm_template_id": "t1"}, {"vcenter_id": "vc1", "vm_template_id": "t1"}),
])
async def test_list_nics_passes_source_params(tools, kwargs, expected_params):
    captured: dict = {}

    async def fake_api_get(path, params=None):
        captured["path"] = path
        captured["params"] = params
        return [{"id": "nic1"}]

    with patch("horizon_mcp.tools.external.api_get", side_effect=fake_api_get):
        result = await tools["list_network_interface_cards"](vcenter_id="vc1", **kwargs)

    assert captured == {"path": "/external/v1/network-interface-cards", "params": expected_params}
    assert result == [{"id": "nic1"}]
