"""Storage backends behind one interface."""

from alexa_mcp_server.config import Settings
from alexa_mcp_server.store.base import Item, Store
from alexa_mcp_server.store.dynamo import DynamoStore
from alexa_mcp_server.store.sqlite import SQLiteStore


def make_store(settings: Settings) -> Store:
    if settings.store == "sqlite":
        return SQLiteStore(settings.sqlite_path)
    if settings.store == "dynamo":
        return DynamoStore(settings.table_name, region=settings.aws_region)
    raise ValueError(f"Unsupported STORE: {settings.store!r}")


__all__ = ["DynamoStore", "Item", "SQLiteStore", "Store", "make_store"]
