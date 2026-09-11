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
