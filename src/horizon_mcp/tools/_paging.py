"""Shared pagination for list tools that take page/size.

The Horizon REST API returns a bare JSON array for paginated list endpoints and the
2606 OpenAPI spec documents no response header or field that says whether more
records exist. So "more may exist" is inferred: a page that came back full
(len(items) >= size) might be followed by another; a short page is the last one.
When the total is an exact multiple of size, has_more is True on the final page and
the next page simply comes back empty.
"""
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

# fetch_all safety cap: stop once either limit is reached and report truncated=True.
FETCH_ALL_MAX_PAGES = 10
FETCH_ALL_MAX_ITEMS = 5000

PAGINATION_DOC = (
    "Returns {items, count, page, size, pages_fetched, has_more, next_page, truncated}. "
    "If has_more is true there may be more results: call again with page=next_page "
    "(or narrow the filter), or pass fetch_all=true to fetch pages automatically "
    f"(stops after {FETCH_ALL_MAX_PAGES} pages or {FETCH_ALL_MAX_ITEMS} items and sets truncated=true). "
    "Never treat a result with has_more=true as the complete list."
)

FETCH_ALL_DOC = (
    f"Fetch successive pages automatically (up to {FETCH_ALL_MAX_PAGES} pages / "
    f"{FETCH_ALL_MAX_ITEMS} items). Prefer a filter when you only need a subset."
)


def paginated(fn: F) -> F:
    """Append the shared pagination note to a list tool's docstring (its MCP description).

    Apply below @mcp.tool so the note is in place before FastMCP reads the docstring.
    """
    fn.__doc__ = inspect.cleandoc(fn.__doc__ or "") + "\n\n" + PAGINATION_DOC
    return fn


async def paginate(
    get: Callable[[str, dict[str, Any]], Awaitable[Any]],
    path: str,
    params: dict[str, Any],
    page: int,
    size: int,
    fetch_all: bool = False,
) -> dict[str, Any]:
    """Fetch one page (or, with fetch_all, successive pages up to the cap) of a list endpoint.

    `get` is the caller module's api_get, passed in so tests that patch
    horizon_mcp.tools.<module>.api_get keep working.
    """
    if page < 1:
        raise ValueError(f"page must be >= 1 (got {page})")
    if size < 1:
        raise ValueError(f"size must be >= 1 (got {size})")

    items: list[Any] = []
    current = page
    pages_fetched = 0
    has_more = False
    while True:
        batch = await get(path, {**params, "page": current, "size": size}) or []
        if not isinstance(batch, list):
            raise ValueError(f"GET {path} returned {type(batch).__name__}, expected a list")
        items.extend(batch)
        pages_fetched += 1
        has_more = len(batch) >= size
        if not fetch_all or not has_more:
            break
        if pages_fetched >= FETCH_ALL_MAX_PAGES or len(items) >= FETCH_ALL_MAX_ITEMS:
            break
        current += 1

    return {
        "items": items,
        "count": len(items),
        "page": page,
        "size": size,
        "pages_fetched": pages_fetched,
        "has_more": has_more,
        "next_page": current + 1 if has_more else None,
        "truncated": fetch_all and has_more,
    }
