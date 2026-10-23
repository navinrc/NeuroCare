"""Simulator web app: the Echo Show page and its JSON API (spec §5.9).

Routes:
- ``GET /``                      the page
- ``GET /sim/state``             linked?, due reminders (the page polls it)
- ``POST /sim/turn``             ``{text, tz}`` → reply, tool calls (dev panel), crisis, link prompt
- ``GET /sim/link``              → Cognito authorize (PKCE S256)
- ``GET /sim/callback``          code exchange → back to ``/``
- ``POST /sim/unlink``           forget the tokens
- ``POST /sim/reminders/{id}/ack``  mark a fired reminder as seen
"""

import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from alexa_sim import oauth
from alexa_sim.agent import BedrockModel, Model, connect, run_turn
from alexa_sim.config import SimSettings
from alexa_sim.sessions import DynamoSessions, MemorySessions, Session, SessionStore, new_session

log = logging.getLogger(__name__)

COOKIE = "sim_session"
MAX_TEXT = 1000
PAGE = Path(__file__).parent / "static" / "index.html"


@dataclass
class Sim:
    """Everything the routes need; tests build one with fakes."""

    settings: SimSettings
    store: SessionStore
    model: Model
    mcp_target: Any
    """The server URL, or an in-process ``MCPServer`` (tests)."""
    clock: Callable[[], float] = time.time
    post: oauth.Post = oauth.post_form


def _session(sim: Sim, request: Request) -> tuple[Session, bool]:
    session_id = request.cookies.get(COOKIE, "")
    session = sim.store.get(session_id) if session_id else None
    return (session, False) if session else (new_session(), True)


def _respond(sim: Sim, session: Session, response: Response, is_new: bool) -> Response:
    sim.store.save(session)
    if is_new:
        response.set_cookie(
            COOKIE,
            session.id,
            max_age=30 * 24 * 3600,
            httponly=True,
            secure=sim.settings.public_url.startswith("https://"),
            samesite="lax",
        )
    return response


def _public(reminder: dict[str, Any]) -> dict[str, Any]:
    return {"id": reminder["id"], "text": reminder["text"], "due_at": reminder["due_at"]}


def build_app(sim: Sim) -> Starlette:
    async def page(request: Request) -> Response:
        return FileResponse(PAGE, headers={"Cache-Control": "no-store"})

    async def state(request: Request) -> Response:
        session, is_new = _session(sim, request)
        now = sim.clock()
        body = {
            "linked": bool(sim.settings.static_token) or session.linked,
            "can_link": sim.settings.can_link,
            "due": [_public(r) for r in session.due_reminders(now)],
            "upcoming": [_public(r) for r in session.reminders if not r.get("acked") and r["due_at"] > now],
            "now": now,
        }
        return _respond(sim, session, JSONResponse(body), is_new)

    async def turn(request: Request) -> Response:
        session, is_new = _session(sim, request)
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            return JSONResponse({"error": f"text must be 1 to {MAX_TEXT} characters"}, 400)
        tz = payload.get("tz") if isinstance(payload.get("tz"), str) else "UTC"
        now = sim.clock()

        def open_tools() -> Any:
            token = oauth.access_token(session, sim.settings, now, sim.post)  # LinkRequired before connecting
            return connect(sim.mcp_target, token)

        result = await run_turn(text.strip(), session, model=sim.model, open_tools=open_tools, now=now, tz=tz)
        body = asdict(result)
        body["reminders_set"] = [_public(r) for r in result.reminders_set]
        return _respond(sim, session, JSONResponse(body), is_new)

    async def link(request: Request) -> Response:
        session, is_new = _session(sim, request)
        if not sim.settings.can_link:
            return JSONResponse({"error": "account linking is not configured"}, 404)
        url = oauth.start_link(session, sim.settings)
        return _respond(sim, session, RedirectResponse(url, 302), is_new)

    async def callback(request: Request) -> Response:
        session, is_new = _session(sim, request)
        code, state_param = request.query_params.get("code", ""), request.query_params.get("state", "")
        try:
            if request.query_params.get("error") or not code:
                raise oauth.OAuthError(request.query_params.get("error", "no code"))
            oauth.finish_link(session, sim.settings, code, state_param, sim.clock(), sim.post)
            target = "/?linked=1"
        except oauth.OAuthError as error:
            log.warning("link failed: %s", error)
            session.oauth = {}
            target = "/?link_error=1"
        return _respond(sim, session, RedirectResponse(target, 302), is_new)

    async def unlink(request: Request) -> Response:
        session, is_new = _session(sim, request)
        oauth.unlink(session)
        session.history = []
        return _respond(sim, session, JSONResponse({"linked": False}), is_new)

    async def ack(request: Request) -> Response:
        session, is_new = _session(sim, request)
        for reminder in session.reminders:
            if reminder["id"] == request.path_params["reminder_id"]:
                reminder["acked"] = True
        return _respond(sim, session, JSONResponse({"ok": True}), is_new)

    return Starlette(
        routes=[
            Route("/", page),
            Route("/sim/state", state),
            Route("/sim/turn", turn, methods=["POST"]),
            Route("/sim/link", link),
            Route("/sim/callback", callback),
            Route("/sim/unlink", unlink, methods=["POST"]),
            Route("/sim/reminders/{reminder_id}/ack", ack, methods=["POST"]),
        ]
    )


def resolve_client(settings: SimSettings) -> SimSettings:
    """Read the ``alexa-plus`` client id and secret from the pool when they aren't configured.

    The client's callback URL depends on the simulator's URL, so CloudFormation can't pass the
    client into the simulator's environment without a cycle.
    """
    if settings.client_id or not settings.user_pool_id:
        return settings
    import boto3

    cognito = boto3.client("cognito-idp", region_name=settings.region)
    clients = cognito.list_user_pool_clients(UserPoolId=settings.user_pool_id, MaxResults=60)["UserPoolClients"]
    match = next((c for c in clients if c["ClientName"] == "alexa-plus"), None)
    if match is None:
        return settings
    detail = cognito.describe_user_pool_client(UserPoolId=settings.user_pool_id, ClientId=match["ClientId"])
    return replace(
        settings, client_id=match["ClientId"], client_secret=detail["UserPoolClient"].get("ClientSecret", "")
    )


def make_sim(settings: SimSettings) -> Sim:
    settings = resolve_client(settings)
    store: SessionStore = DynamoSessions(settings.table, settings.region) if settings.table else MemorySessions()
    return Sim(
        settings=settings,
        store=store,
        model=BedrockModel(settings.model_id, settings.region),
        mcp_target=settings.mcp_url,
    )
