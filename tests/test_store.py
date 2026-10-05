import time

from alexa_mcp_server.store import SQLiteStore


def test_put_get_query_delete():
    store = SQLiteStore(":memory:")
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


def test_put_replaces_and_ignores_key_fields_in_doc():
    store = SQLiteStore(":memory:")
    item = store.put("USER#a", "MEM#1", {"text": "v1"})
    store.put("USER#a", "MEM#1", {**item, "text": "v2"})
    assert store.get("USER#a", "MEM#1")["text"] == "v2"


def test_expired_items_are_hidden():
    store = SQLiteStore(":memory:")
    store.put("USER#a", "TOPIC#1", {"text": "old"}, ttl=int(time.time()) - 1)
    store.put("USER#a", "TOPIC#2", {"text": "fresh"}, ttl=int(time.time()) + 60)
    assert store.get("USER#a", "TOPIC#1") is None
    assert [i["text"] for i in store.query("USER#a", "TOPIC#")] == ["fresh"]


def test_file_backed_store_persists(tmp_path):
    path = str(tmp_path / "sub" / "db.sqlite3")
    SQLiteStore(path).put("USER#a", "MEM#1", {"text": "kept"})
    assert SQLiteStore(path).get("USER#a", "MEM#1")["text"] == "kept"
