"""Phase 6: Cognito JWTs, Protected Resource Metadata, and the Lambda adapter, end to end."""

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from alexa_mcp_server import auth, lambda_handler, server
from alexa_mcp_server.config import Settings
from alexa_mcp_server.lambda_handler import LambdaASGI
from alexa_mcp_server.refine import JOBS, LambdaRefiner

POOL = "us-east-1_TEST"
CLIENT = "alexa-client"
SCOPE = "neurocare/tools"
ISSUER = auth.cognito_issuer("us-east-1", POOL)
BASE = "https://abc123.lambda-url.us-east-1.on.aws"
HOST = "abc123.lambda-url.us-east-1.on.aws"


def _keypair(kid: str) -> tuple[rsa.RSAPrivateKey, dict]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return key, {**jwk, "kid": kid, "alg": "RS256", "use": "sig"}


KEY, JWK = _keypair("k1")
OTHER_KEY, _ = _keypair("k1")


def token(*, key=KEY, kid="k1", **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": "user-sub-123",
        "iss": ISSUER,
        "client_id": CLIENT,
        "token_use": "access",
        "scope": f"openid {SCOPE}",
        "iat": now,
        "exp": now + 3600,
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def verifier():
    calls = []

    def fetch():
        calls.append(1)
        return {"keys": [JWK]}

    v = auth.CognitoTokenVerifier(ISSUER, CLIENT, required_scope=SCOPE, fetch_jwks=fetch)
    v.calls = calls
    return v


def test_valid_access_token_maps_sub_to_user(verifier):
    access = verifier.check(token())
    assert access is not None
    assert access.subject == "user-sub-123" and access.client_id == CLIENT and SCOPE in access.scopes


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 120},  # expired (past the 30 s leeway)
        {"client_id": "someone-else"},  # wrong client
        {"iss": auth.cognito_issuer("us-east-1", "us-east-1_OTHER")},  # another pool
        {"token_use": "id"},  # an ID token, not an access token
        {"scope": "openid"},  # missing the required scope
        {"sub": None},  # no subject
        {"key": OTHER_KEY},  # signed by a key not in the JWKS
        {"kid": "unknown"},  # unknown key id
    ],
    ids=["expired", "wrong-client", "wrong-issuer", "id-token", "no-scope", "no-sub", "bad-signature", "unknown-kid"],
)
def test_bad_tokens_are_rejected(verifier, overrides):
    assert verifier.check(token(**overrides)) is None


def test_garbage_and_hs256_are_rejected(verifier):
    assert verifier.check("not-a-jwt") is None
    forged = jwt.encode({"sub": "x", "iss": ISSUER}, "s" * 32, algorithm="HS256", headers={"kid": "k1"})
    assert verifier.check(forged) is None


def test_jwks_is_cached_and_unknown_kid_refetch_is_rate_limited(verifier):
    assert verifier.check(token()) and verifier.check(token())
    assert len(verifier.calls) == 1
    verifier.check(token(kid="rotated"))
    verifier.check(token(kid="rotated"))
    assert len(verifier.calls) == 1  # within JWKS_REFRESH_SECONDS of the last fetch


def test_build_auth_with_cognito():
    settings = Settings(public_base_url=BASE, cognito_user_pool_id=POOL, cognito_client_id=CLIENT, cognito_scope=SCOPE)
    verifier, settings_out = auth.build_auth(settings)
    assert isinstance(verifier, auth.CognitoTokenVerifier)
    assert str(settings_out.issuer_url) == ISSUER
    assert str(settings_out.resource_server_url) == f"{BASE}/mcp"
    with pytest.raises(RuntimeError):
        auth.build_auth(Settings(cognito_user_pool_id=POOL))
    both, _ = auth.build_auth(
        Settings(cognito_user_pool_id=POOL, cognito_client_id=CLIENT, allow_static_token=True, auth_token="t")
    )
    assert isinstance(both, auth.AnyOfVerifier)


# --- Lambda adapter -------------------------------------------------------------------------------


def event(method: str, path: str, *, body: dict | None = None, headers: dict | None = None) -> dict:
    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"host": HOST, **(headers or {})},
        "requestContext": {"domainName": HOST, "http": {"method": method, "path": path, "sourceIp": "1.2.3.4"}},
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


def rpc(method: str, params: dict | None = None, *, bearer: str | None = None, id_: int = 1) -> dict:
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2025-06-18",
    }
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"
    return event(
        "POST", "/mcp", body={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}, headers=headers
    )


def tool_result(response: dict) -> dict:
    result = json.loads(response["body"])["result"]
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


@pytest.fixture
def authed_app(verifier):
    """A small server with the Cognito verifier, behind the Lambda adapter."""
    settings = Settings(public_base_url=BASE, cognito_user_pool_id=POOL, cognito_client_id=CLIENT, cognito_scope=SCOPE)
    _, auth_settings = auth.build_auth(settings)
    app = MCPServer(name="t", token_verifier=verifier, auth=auth_settings)

    @app.tool()
    def whoami() -> dict:
        return {"user": auth.current_user_id(settings), "speak": "ok"}

    auth.add_root_metadata_route(app, auth_settings, SCOPE)
    asgi = app.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=[HOST], allowed_origins=[BASE]),
        host="0.0.0.0",
    )
    return LambdaASGI(asgi)


def test_protected_resource_metadata_is_served(authed_app):
    for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        response = authed_app(event("GET", path))
        assert response["statusCode"] == 200, path
        doc = json.loads(response["body"])
        assert doc["resource"] == f"{BASE}/mcp"
        assert doc["authorization_servers"] == [ISSUER]
    root = json.loads(authed_app(event("GET", "/.well-known/oauth-protected-resource"))["body"])
    assert root["scopes_supported"] == [SCOPE]


@pytest.mark.parametrize("bearer", [None, "garbage", "expired", "wrong-client"])
def test_unauthorized_carries_www_authenticate(authed_app, bearer):
    tokens = {"expired": token(exp=int(time.time()) - 120), "wrong-client": token(client_id="x")}
    response = authed_app(rpc("tools/list", bearer=tokens.get(bearer, bearer)))
    assert response["statusCode"] == 401
    challenge = response["headers"]["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp"' in challenge


def test_valid_token_calls_tool_as_jwt_subject(authed_app):
    response = authed_app(rpc("tools/call", {"name": "whoami", "arguments": {}}, bearer=token()))
    assert response["statusCode"] == 200, response
    assert response["headers"]["content-type"].startswith("application/json")
    assert tool_result(response)["user"] == "user-sub-123"
    # the container stays warm: a second request reuses the same loop and lifespan
    again = authed_app(rpc("tools/list", bearer=token(), id_=2))
    assert [t["name"] for t in json.loads(again["body"])["result"]["tools"]] == ["whoami"]


def test_wrong_host_is_rejected(authed_app):
    request = rpc("tools/list", bearer=token())
    request["headers"]["host"] = "evil.example"
    assert authed_app(request)["statusCode"] in (403, 421)


def test_real_server_over_the_adapter(mcp_store):
    """The production app (29 tools) through ``build_app``, stateless with JSON responses."""
    app = lambda_handler.LambdaASGI(
        server.mcp.streamable_http_app(
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(allowed_hosts=[HOST], allowed_origins=[BASE]),
            host="0.0.0.0",
        )
    )
    tools = json.loads(app(rpc("tools/list"))["body"])["result"]["tools"]
    assert len(tools) == 29
    response = app(rpc("tools/call", {"name": "start_block", "arguments": {"task": "the slides"}}, id_=2))
    assert "speak" in tool_result(response)


def test_handler_routes_refine_events(monkeypatch):
    seen = []
    monkeypatch.setitem(JOBS, "probe", lambda deps, user_id, ref: seen.append((user_id, ref)))
    monkeypatch.setattr(server, "deps", lambda: None)
    assert lambda_handler.handler({"refine": {"name": "probe", "user_id": "u", "ref": "TASK#1"}}) is None
    assert seen == [("u", "TASK#1")]
    assert lambda_handler.handler({"source": "aws.scheduler"}) is None  # phase 6b; ignored for now


def test_lambda_refiner_self_invokes_async():
    class FakeLambda:
        calls: list = []

        def invoke(self, **kwargs):
            self.calls.append(kwargs)

    client = FakeLambda()
    LambdaRefiner("neurocare-fn", client=client).submit("decode", "u", "INBOX#1")
    (call,) = client.calls
    assert call["FunctionName"] == "neurocare-fn" and call["InvocationType"] == "Event"
    assert json.loads(call["Payload"]) == {"refine": {"name": "decode", "user_id": "u", "ref": "INBOX#1"}}


def test_lambda_refiner_swallows_invoke_errors():
    class Broken:
        def invoke(self, **kwargs):
            raise RuntimeError("throttled")

    LambdaRefiner("fn", client=Broken()).submit("decode", "u", "INBOX#1")  # no raise; baseline stands


def test_response_encoding():
    text = lambda_handler._response(200, [(b"content-type", b"application/json"), (b"set-cookie", b"a=1")], b"{}")
    assert text == {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": "{}",
        "isBase64Encoded": False,
        "cookies": ["a=1"],
    }
    binary = lambda_handler._response(200, [(b"content-type", b"image/png")], b"\x89PNG")
    assert binary["isBase64Encoded"] is True
