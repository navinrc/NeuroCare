"""Storage backends behind one interface."""

from alexa_mcp_server.config import Settings
from alexa_mcp_server.store.base import Item, Store
from alexa_mcp_server.store.sqlite import SQLiteStore


def make_store(settings: Settings) -> Store:
    if settings.store == "sqlite":
        return SQLiteStore(settings.sqlite_path)
    raise ValueError(f"Unsupported STORE: {settings.store!r}")


__all__ = ["Item", "SQLiteStore", "Store", "make_store"]
