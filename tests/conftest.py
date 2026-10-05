from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from alexa_mcp_server import server
from alexa_mcp_server.pillars import memory
from alexa_mcp_server.store import SQLiteStore

NOW = datetime(2026, 10, 5, 18, 10, tzinfo=UTC)  # 2:10 PM in America/New_York
USER = "demo"
SEED = yaml.safe_load((Path(__file__).parents[1] / "profile_seed.yaml").read_text())


@pytest.fixture
def store():
    return SQLiteStore(":memory:")


@pytest.fixture
def seeded(store):
    memory.seed(store, USER, SEED, NOW)
    return store


@pytest.fixture
def mcp_store(store, monkeypatch):
    """The MCP server wired to an in-memory store and a fixed clock."""
    monkeypatch.setattr(server, "_store", store)
    monkeypatch.setattr(server, "clock", lambda: NOW)
    return store
