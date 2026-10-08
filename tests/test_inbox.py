import pytest
from conftest import NOW, USER
from starlette.testclient import TestClient

from alexa_mcp_server import mcp, server
from alexa_mcp_server.config import Settings
from alexa_mcp_server.pillars import inbox, memory, translator
from alexa_mcp_server.store.base import user_pk


@pytest.fixture
def client(mcp_store):
    return TestClient(mcp.streamable_http_app())


def test_token_issue_lookup_revoke(store):
    token = inbox.issue_inbox_token(store, USER, NOW)
    assert inbox.user_for_inbox_token(store, token) == USER
    assert inbox.user_for_inbox_token(store, token + "x") is None
    assert inbox.user_for_inbox_token(store, "") is None
    assert token not in str(store.query(f"TOKEN#{inbox._hash(token)}"))  # only the hash is stored
    assert inbox.revoke_inbox_tokens(store, USER) == 1
    assert inbox.user_for_inbox_token(store, token) is None


def test_delete_all_revokes_tokens(store):
    token = inbox.issue_inbox_token(store, USER, NOW)
    memory.delete_all(store, USER, confirm=True)
    assert inbox.user_for_inbox_token(store, token) is None


def test_post_inbox_then_decode(client, mcp_store):
    token = inbox.issue_inbox_token(mcp_store, USER, NOW)
    response = client.post(
        "/inbox",
        json={"text": "Can you confirm the venue by Friday?", "sender": "Jordan"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    item_id = response.json()["id"]
    stored = mcp_store.get(user_pk(USER), item_id)
    assert stored["source"] == "shortcut" and stored["decoded_at"] is None

    result = translator.decode(mcp_store, USER, NOW)
    assert result["id"] == item_id and result["sender_source"] == "channel"


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        ({}, {"text": "hi"}, 401),
        ({"Authorization": "Bearer wrong"}, {"text": "hi"}, 401),
        ("token", {"text": ""}, 400),
        ("token", {"text": "x" * 4001}, 400),
        ("token", {"text": "hi", "sender": 5}, 400),
        ("token", ["not", "an", "object"], 400),
    ],
)
def test_post_inbox_rejects(client, mcp_store, headers, body, status):
    if headers == "token":
        headers = {"Authorization": f"Bearer {inbox.issue_inbox_token(mcp_store, USER, NOW)}"}
    assert client.post("/inbox", json=body, headers=headers).status_code == status
    assert mcp_store.query(user_pk(USER), "INBOX#") == []


def test_post_inbox_accepts_static_dev_token(client, mcp_store, monkeypatch):
    monkeypatch.setattr(server, "settings", Settings(allow_static_token=True, auth_token="dev"))
    response = client.post("/inbox", json={"text": "hello"}, headers={"Authorization": "Bearer dev"})
    assert response.status_code == 201
