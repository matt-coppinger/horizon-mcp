"""Tests for paginated list tools (tools/_paging.py and the tools that use it)."""
import json
from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from horizon_mcp.tools import external, inventory
from horizon_mcp.tools._paging import (
    FETCH_ALL_MAX_ITEMS,
    FETCH_ALL_MAX_PAGES,
    PAGINATION_DOC,
)

from .conftest import MockFastMCP

# (module, tool name, endpoint path)
PAGINATED = [
    (inventory, "list_desktop_pools", "/inventory/v13/desktop-pools"),
    (inventory, "list_machines", "/inventory/v1/machines"),
    (inventory, "list_rdsh_farms", "/inventory/v10/farms"),
    (inventory, "list_application_pools", "/inventory/v1/application-pools"),
    (inventory, "list_sessions", "/inventory/v1/sessions"),
    (external, "search_ad_users_or_groups", "/external/v4/ad-users-or-groups"),
    (external, "list_audit_events", "/external/v2/audit-events"),
]
IDS = [name for _, name, _ in PAGINATED]


def _tool(module, name):
    mcp = MockFastMCP()
    module.register(mcp)
    return mcp.tools[name]


class FakeServer:
    """Serves `total` items in pages; records every request."""

    def __init__(self, total: int):
        self.total = total
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        page, size = params["page"], params["size"]
        start = (page - 1) * size
        return [{"id": f"i-{n}"} for n in range(start, min(start + size, self.total))]


def _patch(module, server):
    # Pass FakeServer's bound async __call__ so AsyncMock recognises it as a coroutine function.
    fake = server.__call__ if isinstance(server, FakeServer) else server
    return patch(f"horizon_mcp.tools.{module.__name__.rsplit('.', 1)[1]}.api_get", side_effect=fake)


# ── single page ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("module,name,path", PAGINATED, ids=IDS)
async def test_full_page_reports_has_more(module, name, path):
    server = FakeServer(total=25)
    with _patch(module, server):
        result = await _tool(module, name)(page=1, size=10)

    assert server.calls == [(path, {"page": 1, "size": 10})]
    assert result["count"] == 10 and len(result["items"]) == 10
    assert result["has_more"] is True
    assert result["next_page"] == 2
    assert result["page"] == 1 and result["size"] == 10
    assert result["pages_fetched"] == 1
    assert result["truncated"] is False


@pytest.mark.parametrize("module,name,path", PAGINATED, ids=IDS)
async def test_short_page_is_last(module, name, path):
    server = FakeServer(total=25)
    with _patch(module, server):
        result = await _tool(module, name)(page=3, size=10)

    assert result["count"] == 5
    assert result["has_more"] is False
    assert result["next_page"] is None
    assert result["truncated"] is False


@pytest.mark.parametrize("module,name,path", PAGINATED, ids=IDS)
async def test_empty_or_null_response(module, name, path):
    async def fake_get(path, params=None):
        return None

    with _patch(module, fake_get):
        result = await _tool(module, name)()

    assert result["items"] == [] and result["count"] == 0
    assert result["has_more"] is False and result["next_page"] is None


async def test_exact_multiple_reports_has_more_then_empty_page():
    """No has-more signal in the API, so a full final page still says has_more."""
    server = FakeServer(total=20)
    tool = _tool(inventory, "list_machines")
    with _patch(inventory, server):
        first = await tool(page=2, size=10)
        second = await tool(page=first["next_page"], size=10)

    assert first["has_more"] is True and first["next_page"] == 3
    assert second["items"] == [] and second["has_more"] is False


@pytest.mark.parametrize("kwargs", [{"page": 0}, {"size": 0}, {"page": -1}])
async def test_rejects_non_positive_page_or_size(kwargs):
    with _patch(inventory, FakeServer(total=5)) as mock_get:
        with pytest.raises(ValueError, match="must be >= 1"):
            await _tool(inventory, "list_sessions")(**kwargs)
    mock_get.assert_not_called()


async def test_non_list_response_raises():
    async def fake_get(path, params=None):
        return {"unexpected": True}

    with _patch(inventory, fake_get):
        with pytest.raises(ValueError, match="expected a list"):
            await _tool(inventory, "list_machines")()


# ── params pass through ───────────────────────────────────────────────────────

@pytest.mark.parametrize("name,path", [
    ("list_machines", "/inventory/v1/machines"),
    ("list_sessions", "/inventory/v1/sessions"),
])
async def test_filter_and_sort_params_pass_through(name, path):
    server = FakeServer(total=0)
    flt = '{"type":"Equals","name":"state","value":"AVAILABLE"}'
    with _patch(inventory, server):
        await _tool(inventory, name)(page=2, size=50, filter=flt, sort_by="name", order_by="DESC")

    assert server.calls == [(path, {
        "page": 2, "size": 50, "filter": flt, "sort_by": "name", "order_by": "DESC",
    })]


@pytest.mark.parametrize("module,name,path", PAGINATED, ids=IDS)
async def test_filter_passes_through_on_every_page(module, name, path):
    server = FakeServer(total=25)
    flt = '{"type":"Contains","name":"name","value":"x"}'
    with _patch(module, server):
        await _tool(module, name)(size=10, filter=flt, fetch_all=True)

    assert [c[1] for c in server.calls] == [
        {"page": p, "size": 10, "filter": flt} for p in (1, 2, 3)
    ]


async def test_empty_optional_params_are_not_sent():
    server = FakeServer(total=0)
    with _patch(inventory, server):
        await _tool(inventory, "list_machines")()
    assert server.calls[0][1] == {"page": 1, "size": 100}


async def test_search_ad_default_size_is_50():
    server = FakeServer(total=0)
    with _patch(external, server):
        await _tool(external, "search_ad_users_or_groups")()
    assert server.calls[0][1] == {"page": 1, "size": 50}


# ── fetch_all ─────────────────────────────────────────────────────────────────

async def test_fetch_all_stops_at_short_page():
    server = FakeServer(total=25)
    with _patch(inventory, server):
        result = await _tool(inventory, "list_machines")(size=10, fetch_all=True)

    assert [c[1]["page"] for c in server.calls] == [1, 2, 3]
    assert result["count"] == 25
    assert [i["id"] for i in result["items"]] == [f"i-{n}" for n in range(25)]
    assert result["pages_fetched"] == 3
    assert result["has_more"] is False and result["next_page"] is None
    assert result["truncated"] is False


async def test_fetch_all_starts_at_given_page():
    server = FakeServer(total=25)
    with _patch(inventory, server):
        result = await _tool(inventory, "list_machines")(page=2, size=10, fetch_all=True)

    assert [c[1]["page"] for c in server.calls] == [2, 3]
    assert result["count"] == 15 and result["page"] == 2


async def test_fetch_all_page_cap_sets_truncated():
    server = FakeServer(total=10_000)
    with _patch(inventory, server):
        result = await _tool(inventory, "list_sessions")(size=10, fetch_all=True)

    assert len(server.calls) == FETCH_ALL_MAX_PAGES
    assert result["count"] == 10 * FETCH_ALL_MAX_PAGES
    assert result["truncated"] is True
    assert result["has_more"] is True
    assert result["next_page"] == FETCH_ALL_MAX_PAGES + 1


async def test_fetch_all_item_cap_sets_truncated():
    server = FakeServer(total=100_000)
    with _patch(inventory, server):
        result = await _tool(inventory, "list_machines")(size=1000, fetch_all=True)

    assert len(server.calls) == FETCH_ALL_MAX_ITEMS // 1000
    assert result["count"] == FETCH_ALL_MAX_ITEMS
    assert result["truncated"] is True
    assert result["next_page"] == FETCH_ALL_MAX_ITEMS // 1000 + 1


async def test_fetch_all_exactly_at_cap_boundary_without_more_data():
    """Data ends exactly at the page cap — the cap is hit, so it still reports truncated."""
    server = FakeServer(total=10 * FETCH_ALL_MAX_PAGES)
    with _patch(inventory, server):
        result = await _tool(inventory, "list_machines")(size=10, fetch_all=True)
    assert result["count"] == 10 * FETCH_ALL_MAX_PAGES
    assert result["truncated"] is True and result["next_page"] == FETCH_ALL_MAX_PAGES + 1


# ── tool descriptions (real FastMCP registration) ─────────────────────────────

@pytest.mark.parametrize("module,name,path", PAGINATED, ids=IDS)
async def test_description_and_schema_document_pagination(module, name, path):
    mcp = FastMCP("test")
    module.register(mcp)
    tool = await mcp.get_tool(name)

    assert PAGINATION_DOC in tool.description
    # original docstring text survives, dedented
    assert not tool.description.startswith(" ")
    props = tool.parameters["properties"]
    assert {"page", "size", "fetch_all"} <= set(props)
    assert props["fetch_all"]["default"] is False
    json.dumps(tool.parameters)
