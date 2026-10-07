"""MCP server entrypoint: a thin tool layer over the pillar functions.

Exposes tools over the Streamable HTTP transport at ``http://<host>:<port>/mcp``.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from alexa_mcp_server import auth
from alexa_mcp_server.config import load_settings
from alexa_mcp_server.pillars import memory
from alexa_mcp_server.store import Store, make_store

INSTRUCTIONS = """\
You are connected to a personal cognitive support server for this user.

- When the user returns after a break or asks what they were doing, call what_was_i_doing.
- When the user asks you to remember something, call remember. Use kind=person for who someone is,
  kind=commitment for something they promised or need to do.
- When the user asks what they told you, or what they know about something, call recall.
- When the user says something is done or handled, call close_loop with their words.
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
clock: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731 — tests replace it


def get_store() -> Store:
    global _store
    if _store is None:
        _store = make_store(settings)
    return _store


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
    return memory.remember(get_store(), _user(), text, clock(), kind=kind, subject=subject, due_at=due_at)


@mcp.tool(annotations=READ_ONLY)
def recall(
    query: Annotated[str, Field(description="What the user is asking about, in their words")],
    kind: Kind | None = None,
    limit: Annotated[int, Field(ge=1, le=20)] = 5,
) -> dict[str, Any]:
    """Find what the user told you before. An empty `matches` list means nothing was saved about it."""
    return memory.recall(get_store(), _user(), query, clock(), kind=kind, limit=limit)


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
    return memory.close_loop(get_store(), _user(), text, clock())


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
