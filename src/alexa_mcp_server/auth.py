"""Bearer-token auth.

Phase 1 supports only the static dev token (``AUTH_TOKEN``, enabled by ``ALLOW_STATIC_TOKEN=true``).
Cognito JWT verification arrives in phase 6.
"""

import hmac

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

from alexa_mcp_server.config import Settings


class StaticTokenVerifier:
    """Accepts exactly one shared token and maps it to the demo user."""

    def __init__(self, token: str, user_id: str):
        self._token = token.encode()
        self._user_id = user_id

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token.encode(), self._token):
            return None
        return AccessToken(token=token, client_id="static-dev", scopes=[], subject=self._user_id)


def build_auth(settings: Settings) -> tuple[TokenVerifier | None, AuthSettings | None]:
    if not settings.allow_static_token:
        return None, None
    if not settings.auth_token:
        raise RuntimeError("ALLOW_STATIC_TOKEN=true requires AUTH_TOKEN")
    auth = AuthSettings(
        issuer_url=settings.public_base_url,
        resource_server_url=f"{settings.public_base_url}/mcp",
        validate_token_resource=False,
    )
    return StaticTokenVerifier(settings.auth_token, settings.demo_user_id), auth


def current_user_id(settings: Settings) -> str:
    """The caller's user id.

    Over HTTP with auth enabled, the transport rejects requests without a valid token, so a
    missing token here means auth is disabled or the call is in-process (tests).
    """
    token = get_access_token()
    if token is None:
        return settings.demo_user_id
    return token.subject or token.client_id
