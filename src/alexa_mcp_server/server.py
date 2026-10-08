"""MCP server entrypoint: a thin tool layer over the pillar functions.

Exposes tools over the Streamable HTTP transport at ``http://<host>:<port>/mcp``.
"""

import hmac
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from alexa_mcp_server import auth, semantic  # noqa: F401 — semantic registers the "embed" refine job
from alexa_mcp_server.config import load_settings
from alexa_mcp_server.llm import LLM, Embedder, make_embedder, make_llm
from alexa_mcp_server.pillars import inbox, memory, sense_of_time, translator
from alexa_mcp_server.refine import Deps, Refiner, ThreadRefiner
from alexa_mcp_server.store import Store, make_store

INSTRUCTIONS = """\
You are connected to a personal cognitive support server for this user.

- When the user returns after a break or asks what they were doing, call what_was_i_doing.
- When the user asks you to remember something, call remember. Use kind=person for who someone is,
  kind=commitment for something they promised or need to do.
- When the user asks what they told you, or what they know about something, call recall.
- When the user says something is done or handled, call close_loop with their words.
- When the user asks the time, what's next, or how long they have, call now_context.
- When the user starts or finishes a piece of work, call start_block or end_block.
- When the user asks how long they've been at something, call check_in.
- When a tool result includes suggest_reminder_minutes, offer to set an Alexa reminder for that time.
- When the user asks what a message means, call decode. If they refer to a message they just
  sent or forwarded, call decode with no message.
- When decode returns needs_work or reply_needed, make at most one offer: a reminder or a breakdown.
- After a decode, when the user asks what to say or what the sender wants, call decode_result.
- When the user asks "what needs me?" or "anything urgent?", call triage_inbox.
- Speak the `speak` field from tool results in plain, literal words. Do not add idioms.
- Prefer accuracy over agreement. If the user's claim conflicts with what memory shows, say so gently.
"""

settings = load_settings()
_token_verifier, _auth_settings = auth.build_auth(settings)

mcp = MCPServer(
    name="neurocare",
    instructions=INSTRUCTIONS,
    token_verifier=_token_verifier,
    auth=_auth_settings,
)

_store: Store | None = None
_llm: LLM | None = None
_embedder: Embedder | None = None
_refiner: Refiner | None = None
clock: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731 — tests replace it


def get_store() -> Store:
    global _store
    if _store is None:
        _store = make_store(settings)
    return _store


def get_embedder() -> Embedder | None:
    global _embedder
    if _embedder is None:
        _embedder = make_embedder(settings)
    return _embedder


def deps() -> Deps:
    global _llm
    if _llm is None:
        _llm = make_llm(settings)
    return Deps(store=get_store(), llm=_llm, embedder=get_embedder(), clock=lambda: clock())


def get_refiner() -> Refiner:
    """Background refine jobs (spec §4). The Lambda self-invoke runner replaces this in phase 6."""
    global _refiner
    if _refiner is None:
        _refiner = ThreadRefiner(deps())
    return _refiner


def _user() -> str:
    return auth.current_user_id(settings)


READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

Kind = Literal["fact", "person", "preference", "commitment"]


@mcp.tool(annotations=READ_ONLY)
def ping() -> str:
    """Health check. Returns 'pong'."""
    return "pong"


@mcp.tool(annotations=WRITE)
def remember(
    text: Annotated[str, Field(description="What to remember, in the user's words", max_length=2000)],
    kind: Annotated[Kind, Field(description="commitment = something to do; it becomes an open loop")] = "fact",
    subject: Annotated[str | None, Field(description="Person or project it's about; for person, their name")] = None,
    due_at: Annotated[str | None, Field(description="Local ISO 8601; bare date = 9 AM. Commitments only")] = None,
) -> dict[str, Any]:
    """Store something the user wants kept: a fact, a person, a preference, or a commitment."""
    return memory.remember(
        get_store(), _user(), text, clock(), kind=kind, subject=subject, due_at=due_at, refiner=get_refiner()
    )


@mcp.tool(annotations=READ_ONLY)
def recall(
    query: Annotated[str, Field(description="What the user is asking about, in their words")],
    kind: Kind | None = None,
    limit: Annotated[int, Field(ge=1, le=20)] = 5,
) -> dict[str, Any]:
    """Find what the user told you before. An empty `matches` list means nothing was saved about it."""
    return memory.recall(get_store(), _user(), query, clock(), kind=kind, limit=limit, embedder=get_embedder())


@mcp.tool(annotations=READ_ONLY)
def what_was_i_doing() -> dict[str, Any]:
    """Restore context after an interruption: current work, recent memories, and open loops."""
    return memory.what_was_i_doing(get_store(), _user(), clock())


@mcp.tool(annotations=READ_ONLY)
def open_loops(limit: Annotated[int, Field(ge=1, le=20)] = 5) -> dict[str, Any]:
    """Unfinished commitments, soonest due first."""
    return memory.open_loops(get_store(), _user(), clock(), limit=limit)


@mcp.tool(annotations=WRITE)
def close_loop(text: Annotated[str, Field(description="The finished item, in the user's words")]) -> dict[str, Any]:
    """Mark an open loop done. If several match, nothing is closed and `candidates` lists them; ask which one."""
    return memory.close_loop(get_store(), _user(), text, clock(), embedder=get_embedder())


@mcp.tool(annotations=READ_ONLY)
def get_profile() -> dict[str, Any]:
    """The user's profile: name, time zone, style, thresholds, and the people they've told you about."""
    return memory.get_profile(get_store(), _user())


@mcp.tool(annotations=WRITE)
def set_preference(
    key: Annotated[str, Field(description="Dotted profile path, e.g. time.end_of_day or style.register")],
    value: Annotated[str | int | bool | list[str] | None, Field(description="New value")],
) -> dict[str, Any]:
    """Change one profile setting. The value is checked against the setting's type and range."""
    return memory.set_preference(get_store(), _user(), key, value, clock())


@mcp.tool(annotations=READ_ONLY)
def export_all() -> dict[str, Any]:
    """Every item stored for the user, as structured data."""
    return memory.export_all(get_store(), _user())


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
def delete_all(confirm: bool = False) -> dict[str, Any]:
    """Delete everything stored for the user. Irreversible: call with confirm=true only after the user says yes."""
    return memory.delete_all(get_store(), _user(), confirm=confirm)


@mcp.tool(annotations=READ_ONLY)
def now_context() -> dict[str, Any]:
    """The time, energy zone, current work block, and next commitment with a leave-by time when travel is known."""
    return sense_of_time.now_context(get_store(), _user(), clock())


@mcp.tool(annotations=WRITE)
def start_block(
    task: Annotated[str, Field(description="The work being started, in the user's words", max_length=200)],
) -> dict[str, Any]:
    """Start timing a piece of work. A different open block is closed and reported in `auto_closed`."""
    return sense_of_time.start_block(get_store(), _user(), task, clock())


@mcp.tool(annotations=WRITE)
def end_block(
    summary: Annotated[str | None, Field(description="What got done, if the user said", max_length=500)] = None,
) -> dict[str, Any]:
    """Stop timing the current piece of work."""
    return sense_of_time.end_block(get_store(), _user(), clock(), summary=summary)


@mcp.tool(annotations=READ_ONLY)
def check_in() -> dict[str, Any]:
    """How long the current block has run, as a level: none, gentle, nudge, or hard."""
    return sense_of_time.check_in(get_store(), _user(), clock())


@mcp.tool(annotations=WRITE)
def decode(
    message: Annotated[
        str | None,
        Field(description="The message the user received. Omit to read the newest forwarded one", max_length=4000),
    ] = None,
    sender: Annotated[str | None, Field(description="Who sent it, if the user said", max_length=200)] = None,
) -> dict[str, Any]:
    """Explain what a message most likely means, how urgent it is, and what it asks for."""
    return translator.decode(get_store(), _user(), clock(), message=message, sender=sender, refiner=get_refiner())


@mcp.tool(annotations=READ_ONLY)
def decode_result() -> dict[str, Any]:
    """The details of the last decoded message: summary, what they want, and a suggested reply."""
    return translator.decode_result(get_store(), _user())


@mcp.tool(annotations=WRITE)
def triage_inbox(limit: Annotated[int, Field(ge=1, le=10)] = 3) -> dict[str, Any]:
    """What needs the user: open messages ranked by priority, then reply-by time, then age."""
    return translator.triage_inbox(get_store(), _user(), clock(), limit=limit, refiner=get_refiner())


def _inbox_user(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        return None
    user_id = inbox.user_for_inbox_token(get_store(), token)
    if user_id is None and settings.allow_static_token and settings.auth_token:
        if hmac.compare_digest(token.encode(), settings.auth_token.encode()):
            user_id = settings.demo_user_id
    return user_id


@mcp.custom_route("/inbox", methods=["POST"])
async def post_inbox(request: Request) -> JSONResponse:
    """Forward a message for a later decode (iOS Shortcut). Auth: personal inbox token."""
    user_id = _inbox_user(request)
    if user_id is None:
        return JSONResponse({"error": {"code": "UNAUTHORIZED", "message": "valid inbox token required"}}, 401)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return JSONResponse({"error": {"code": "INVALID_ARGUMENT", "message": "JSON object body required"}}, 400)
    text, sender, source = body.get("text"), body.get("sender"), body.get("source") or "shortcut"
    problems = []
    if not isinstance(text, str) or not text.strip() or len(text) > translator.MAX_MESSAGE:
        problems.append(f"text must be 1 to {translator.MAX_MESSAGE} characters")
    if sender is not None and (not isinstance(sender, str) or len(sender) > 200):
        problems.append("sender must be a string of at most 200 characters")
    if not isinstance(source, str) or len(source) > 40:
        problems.append("source must be a short string")
    if problems:
        return JSONResponse({"error": {"code": "INVALID_ARGUMENT", "message": "; ".join(problems)}}, 400)
    item = translator.add_inbox_item(get_store(), user_id, text.strip(), clock(), sender=sender, source=source)
    return JSONResponse({"id": item["sk"]}, 201)


@mcp.resource("profile://me", name="profile", mime_type="application/json")
def profile_resource() -> str:
    """The user's profile (same data as get_profile)."""
    profile = memory.get_profile(get_store(), _user())
    profile.pop("speak")
    return json.dumps(profile)


def main() -> None:
    if _auth_settings is None:
        logging.getLogger(__name__).warning("Auth disabled: every request is served as user %r", settings.demo_user_id)
    mcp.run(transport="streamable-http", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
