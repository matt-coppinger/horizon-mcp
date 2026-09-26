"""Shared test fixtures and utilities."""
import os
import pytest

# Set required env vars before any horizon_mcp imports
os.environ.setdefault("HORIZON_BASE_URL", "https://horizon.test.example.com")
os.environ.setdefault("HORIZON_ACCESS_TOKEN", "test-token-abc123")


class MockFastMCP:
    """Minimal FastMCP stand-in that captures registered tool callables by name."""

    def __init__(self) -> None:
        self.tools: dict = {}
        self.annotations: dict = {}

    def tool(self, *args, annotations=None, **kwargs):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            self.annotations[fn.__name__] = annotations
            return fn
        return decorator


@pytest.fixture
def mock_mcp() -> MockFastMCP:
    return MockFastMCP()


_CONFIRM_MODULES = ("inventory", "helpdesk", "entitlements", "config")


@pytest.fixture(autouse=True)
def confirmations(monkeypatch):
    """Stand in for the user approving every confirmation prompt.

    Tools call require_confirmation() before destructive actions; with no MCP client
    attached it would refuse. This records each prompt so tests can assert on it.
    Set `confirmations.approve = False` to simulate the user declining.
    """
    from horizon_mcp.tools._confirm import ConfirmationRequired

    class Recorder(list):
        approve = True

    rec = Recorder()

    async def fake(summary, *, confirm=False):
        rec.append(summary)
        if not rec.approve:
            raise ConfirmationRequired(f"Cancelled by the user — nothing was changed. ({summary})")

    async def fake_label(path, resource_id):
        return resource_id

    async def fake_changes(path, spec):
        return f"fields: {', '.join(sorted(spec))}"

    for mod in _CONFIRM_MODULES:
        monkeypatch.setattr(f"horizon_mcp.tools.{mod}.require_confirmation", fake)
    monkeypatch.setattr("horizon_mcp.tools.inventory._label", fake_label)
    monkeypatch.setattr("horizon_mcp.tools.config._describe_changes", fake_changes)
    return rec


@pytest.fixture(autouse=True)
def no_stored_refresh_token(monkeypatch):
    """Start every test without a server-side refresh token (it's module state in client.py)."""
    monkeypatch.setattr("horizon_mcp.client._refresh_token", None)
