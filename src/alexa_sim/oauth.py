"""Account linking the way Alexa+ does it: auth code + PKCE S256 + refresh tokens (spec §5.9).

The simulator is a confidential client (``alexa-plus``); tokens stay in its session store and only
the session cookie reaches the browser.
"""

import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from alexa_sim.config import SCOPES, SimSettings
from alexa_sim.sessions import Session

REFRESH_MARGIN = 60
"""Refresh an access token this many seconds before it expires."""

Post = Callable[[str, dict[str, str], str], tuple[int, dict[str, Any]]]
"""``(url, form, basic_auth_header) -> (status, json body)``."""


class LinkRequired(Exception):
    """No usable token: the user has to link (or re-link) the account."""


class OAuthError(Exception):
    pass


def post_form(url: str, form: dict[str, str], basic: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode(),
        headers={"Authorization": basic, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 — fixed Cognito URL
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read())
        except ValueError:
            return error.code, {}


def _basic(settings: SimSettings) -> str:
    return "Basic " + base64.b64encode(f"{settings.client_id}:{settings.client_secret}".encode()).decode()


def challenge_for(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def start_link(session: Session, settings: SimSettings) -> str:
    """The Cognito authorize URL; binds a fresh ``state`` and PKCE verifier to the session."""
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    session.oauth = {"state": state, "verifier": verifier}
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "scope": SCOPES,
            "state": state,
            "code_challenge": challenge_for(verifier),
            "code_challenge_method": "S256",
            "resource": settings.mcp_url,
        }
    )
    return f"https://{settings.cognito_domain}/oauth2/authorize?{query}"


def _store(session: Session, body: dict[str, Any], now: float) -> None:
    session.tokens = {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token") or session.tokens.get("refresh_token", ""),
        "expires_at": now + int(body.get("expires_in", 3600)),
    }


def finish_link(
    session: Session, settings: SimSettings, code: str, state: str, now: float, post: Post = post_form
) -> None:
    """Exchange the code. The pending ``state`` is single use: it is cleared before the exchange."""
    pending, session.oauth = session.oauth, {}
    if not pending or not state or not secrets.compare_digest(state, pending.get("state", "")):
        raise OAuthError("state mismatch")
    status, body = post(
        f"https://{settings.cognito_domain}/oauth2/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.redirect_uri,
            "code_verifier": pending["verifier"],
        },
        _basic(settings),
    )
    if status != 200 or "access_token" not in body:
        raise OAuthError(f"token exchange failed: {status} {body.get('error', '')}")
    _store(session, body, now)


def access_token(session: Session, settings: SimSettings, now: float, post: Post = post_form) -> str:
    """A usable access token, refreshed when it is about to expire. Raises ``LinkRequired``."""
    if settings.static_token:
        return settings.static_token
    tokens = session.tokens
    if not tokens:
        raise LinkRequired()
    if tokens.get("access_token") and tokens.get("expires_at", 0) - REFRESH_MARGIN > now:
        return tokens["access_token"]
    if not tokens.get("refresh_token"):
        session.tokens = {}
        raise LinkRequired()
    status, body = post(
        f"https://{settings.cognito_domain}/oauth2/token",
        {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": settings.client_id},
        _basic(settings),
    )
    if status != 200 or "access_token" not in body:
        session.tokens = {}
        raise LinkRequired()
    _store(session, body, now)
    return session.tokens["access_token"]


def unlink(session: Session) -> None:
    session.tokens, session.oauth = {}, {}
