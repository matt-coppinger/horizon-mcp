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

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


@pytest.fixture
def mock_mcp() -> MockFastMCP:
    return MockFastMCP()
