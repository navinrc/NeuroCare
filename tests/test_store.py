import time

import pytest
from conftest import TABLE, create_table

from alexa_mcp_server.store import DynamoStore, SQLiteStore


@pytest.fixture
def live_store(backend, request):
    """A store on the real clock, for the TTL test."""
    if backend == "sqlite":
        return SQLiteStore(":memory:")
    request.getfixturevalue("aws")
    create_table()
    return DynamoStore(TABLE)


def test_put_get_query_delete(live_store):
    store = live_store
    store.put("USER#a", "MEM#2", {"text": "two"})
    store.put("USER#a", "MEM#1", {"text": "one"})
    store.put("USER#a", "PROFILE", {"doc": {}})
    store.put("USER#b", "MEM#1", {"text": "other user"})

    assert store.get("USER#a", "MEM#1") == {"text": "one", "pk": "USER#a", "sk": "MEM#1"}
    assert [i["text"] for i in store.query("USER#a", "MEM#")] == ["one", "two"]
    assert len(store.query("USER#a")) == 3

    store.delete("USER#a", "MEM#1")
    assert store.get("USER#a", "MEM#1") is None
    assert store.delete_partition("USER#a") == 2
    assert store.query("USER#a") == []
    assert store.get("USER#b", "MEM#1") is not None


def test_put_replaces_and_ignores_key_fields_in_doc(live_store):
    store = live_store
    item = store.put("USER#a", "MEM#1", {"text": "v1"})
    store.put("USER#a", "MEM#1", {**item, "text": "v2"})
    assert store.get("USER#a", "MEM#1")["text"] == "v2"


def test_expired_items_are_hidden(live_store):
    store = live_store
    store.put("USER#a", "TOPIC#1", {"text": "old"}, ttl=int(time.time()) - 1)
    store.put("USER#a", "TOPIC#2", {"text": "fresh"}, ttl=int(time.time()) + 60)
    assert store.get("USER#a", "TOPIC#1") is None
    assert [i["text"] for i in store.query("USER#a", "TOPIC#")] == ["fresh"]


def test_file_backed_store_persists(tmp_path):
    path = str(tmp_path / "sub" / "db.sqlite3")
    SQLiteStore(path).put("USER#a", "MEM#1", {"text": "kept"})
    assert SQLiteStore(path).get("USER#a", "MEM#1")["text"] == "kept"


def test_values_round_trip(live_store):
    doc = {
        "int": 3,
        "float": 0.25,
        "whole_float": 2.0,
        "neg": -1.5,
        "none": None,
        "bool": True,
        "empty": "",
        "nested": {"steps": [{"n": 1, "minutes": 5, "done": False}], "tags": ("a", "b")},
    }
    live_store.put("USER#a", "TASK#1", doc)
    got = live_store.get("USER#a", "TASK#1")
    assert got == {**doc, "nested": {**doc["nested"], "tags": ["a", "b"]}, "pk": "USER#a", "sk": "TASK#1"}
    assert type(got["int"]) is int and type(got["whole_float"]) is float


def test_query_pages_through_large_partitions(live_store):
    blob = "x" * 50_000  # DynamoDB returns at most 1 MB per page
    for i in range(30):
        live_store.put("USER#a", f"MEM#{i:03d}", {"text": blob})
    assert len(live_store.query("USER#a", "MEM#")) == 30
    assert live_store.delete_partition("USER#a") == 30
    assert live_store.query("USER#a") == []
