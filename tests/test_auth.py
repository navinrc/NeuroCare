import pytest

from alexa_mcp_server.auth import StaticTokenVerifier, build_auth, current_user_id
from alexa_mcp_server.config import Settings


async def test_static_token_verifier():
    verifier = StaticTokenVerifier("s3cret", "demo")
    token = await verifier.verify_token("s3cret")
    assert token is not None and token.subject == "demo"
    assert await verifier.verify_token("wrong") is None


def test_build_auth():
    assert build_auth(Settings()) == (None, None)
    with pytest.raises(RuntimeError):
        build_auth(Settings(allow_static_token=True))
    verifier, auth = build_auth(Settings(allow_static_token=True, auth_token="t"))
    assert isinstance(verifier, StaticTokenVerifier)
    assert str(auth.resource_server_url) == "http://127.0.0.1:8000/mcp"


def test_in_process_calls_use_demo_user():
    assert current_user_id(Settings(demo_user_id="me")) == "me"


def test_public_base_url_follows_port(monkeypatch):
    from alexa_mcp_server.config import load_settings

    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("PORT", "8765")
    assert load_settings().public_base_url == "http://127.0.0.1:8765"
