"""Bearer-token auth.

- Cognito access tokens (Alexa+ account linking, spec §3): RS256 JWTs checked against the user
  pool's JWKS for issuer, ``token_use``, ``client_id``, expiry, and scope. The JWT ``sub`` is the
  ``user_id``.
- The static dev token (``AUTH_TOKEN``), accepted only with ``ALLOW_STATIC_TOKEN=true``.

The server publishes Protected Resource Metadata (RFC 9728) naming the Cognito issuer, and a 401
carries ``WWW-Authenticate`` with ``resource_metadata`` (both from the MCP SDK when ``AuthSettings``
is set).
"""

import hmac
import json
import logging
import threading
import time
import urllib.request
from collections.abc import Callable
from typing import Any

import anyio
import jwt
from mcp.server.auth.handlers.metadata import ProtectedResourceMetadataHandler
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.shared.auth import ProtectedResourceMetadata
from starlette.requests import Request
from starlette.responses import Response

from alexa_mcp_server.config import Settings

log = logging.getLogger(__name__)

JWKS_REFRESH_SECONDS = 300
"""An unknown ``kid`` refetches the JWKS at most this often (key rotation without a flood)."""

LEEWAY_SECONDS = 30
"""Clock skew allowed on ``exp``."""


class StaticTokenVerifier:
    """Accepts exactly one shared token and maps it to the demo user."""

    def __init__(self, token: str, user_id: str):
        self._token = token.encode()
        self._user_id = user_id

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token.encode(), self._token):
            return None
        return AccessToken(token=token, client_id="static-dev", scopes=[], subject=self._user_id)


def cognito_issuer(region: str, user_pool_id: str) -> str:
    return f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"


def _fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310 — fixed https Cognito URL
        return json.loads(response.read())


class CognitoTokenVerifier:
    """Verifies Cognito access tokens issued to one app client."""

    def __init__(
        self,
        issuer: str,
        client_id: str,
        *,
        required_scope: str = "",
        fetch_jwks: Callable[[], dict[str, Any]] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.issuer = issuer
        self._client_id = client_id
        self._required_scope = required_scope
        self._fetch_jwks = fetch_jwks or (lambda: _fetch_json(f"{issuer}/.well-known/jwks.json"))
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = float("-inf")
        self._lock = threading.Lock()

    def _key(self, kid: str) -> jwt.PyJWK | None:
        with self._lock:
            if kid not in self._keys and self._clock() - self._fetched_at >= JWKS_REFRESH_SECONDS:
                self._fetched_at = self._clock()
                try:
                    jwks = self._fetch_jwks()
                    self._keys = {k["kid"]: jwt.PyJWK(k) for k in jwks.get("keys", []) if "kid" in k}
                except Exception:
                    log.exception("JWKS fetch failed")
            return self._keys.get(kid)

    def warm(self) -> None:
        """Fetch the JWKS ahead of the first request (Lambda init)."""
        self._key("")

    def check(self, token: str) -> AccessToken | None:
        try:
            kid = jwt.get_unverified_header(token).get("kid", "")
        except jwt.PyJWTError:
            return None
        key = self._key(kid)
        if key is None:
            return None
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iss", "sub", "token_use", "client_id"], "verify_aud": False},
            )
        except jwt.PyJWTError as error:
            log.info("rejected token: %s", error)
            return None
        if claims["token_use"] != "access" or not hmac.compare_digest(claims["client_id"], self._client_id):
            return None
        scopes = str(claims.get("scope", "")).split()
        if self._required_scope and self._required_scope not in scopes:
            return None
        return AccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=scopes,
            expires_at=int(claims["exp"]),
            subject=claims["sub"],
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        return await anyio.to_thread.run_sync(self.check, token)


class AnyOfVerifier:
    """Tries each verifier in turn (Cognito, then the static dev token when enabled)."""

    def __init__(self, *verifiers: TokenVerifier):
        self.verifiers = verifiers

    async def verify_token(self, token: str) -> AccessToken | None:
        for verifier in self.verifiers:
            if (access := await verifier.verify_token(token)) is not None:
                return access
        return None


def warm(verifier: TokenVerifier | None) -> None:
    """Fetch Cognito's JWKS ahead of the first request."""
    for each in verifier.verifiers if isinstance(verifier, AnyOfVerifier) else (verifier,):
        if isinstance(each, CognitoTokenVerifier):
            each.warm()


def build_auth(settings: Settings) -> tuple[TokenVerifier | None, AuthSettings | None]:
    verifiers: list[TokenVerifier] = []
    issuer = settings.public_base_url
    if settings.cognito_user_pool_id:
        if not settings.cognito_client_id:
            raise RuntimeError("COGNITO_USER_POOL_ID requires COGNITO_CLIENT_ID")
        issuer = cognito_issuer(settings.aws_region, settings.cognito_user_pool_id)
        verifiers.append(
            CognitoTokenVerifier(issuer, settings.cognito_client_id, required_scope=settings.cognito_scope)
        )
    if settings.allow_static_token:
        if not settings.auth_token:
            raise RuntimeError("ALLOW_STATIC_TOKEN=true requires AUTH_TOKEN")
        verifiers.append(StaticTokenVerifier(settings.auth_token, settings.demo_user_id))
    if not verifiers:
        return None, None
    auth = AuthSettings(
        issuer_url=issuer,
        resource_server_url=f"{settings.public_base_url}/mcp",
        required_scopes=None,  # the Cognito verifier checks the scope; the static token has none
        validate_token_resource=False,  # Cognito access tokens carry no audience; client_id is checked instead
    )
    verifier = verifiers[0] if len(verifiers) == 1 else AnyOfVerifier(*verifiers)
    return verifier, auth


def add_root_metadata_route(mcp: MCPServer, auth: AuthSettings, scope: str = "") -> None:
    """Serve RFC 9728 metadata at ``/.well-known/oauth-protected-resource`` too.

    The SDK serves it at ``/.well-known/oauth-protected-resource/mcp`` (the resource path appended);
    the root path is for clients that look there first (spec §11 phase 6).
    """
    handler = ProtectedResourceMetadataHandler(
        ProtectedResourceMetadata(
            resource=auth.resource_server_url,
            authorization_servers=[auth.issuer_url],
            scopes_supported=[scope] if scope else None,
            resource_name="NeuroCare",
        )
    )

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def protected_resource_metadata(request: Request) -> Response:
        return await handler.handle(request)


def current_user_id(settings: Settings) -> str:
    """The caller's user id.

    Over HTTP with auth enabled, the transport rejects requests without a valid token, so a
    missing token here means auth is disabled or the call is in-process (tests).
    """
    token = get_access_token()
    if token is None:
        return settings.demo_user_id
    return token.subject or token.client_id
