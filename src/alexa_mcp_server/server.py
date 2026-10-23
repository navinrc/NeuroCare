"""MCP server entrypoint: a thin tool layer over the pillar functions.

Exposes tools over the Streamable HTTP transport at ``http://<host>:<port>/mcp``.
"""

import functools
import hmac
import inspect
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from alexa_mcp_server import auth, semantic  # noqa: F401 — semantic registers the "embed" refine job
from alexa_mcp_server.config import load_settings
from alexa_mcp_server.llm import LLM, Embedder, make_embedder, make_guard, make_llm
from alexa_mcp_server.pillars import guardrail, inbox, memory, overrides, plan, sense_of_time, tasks, translator
from alexa_mcp_server.refine import Deps, LambdaRefiner, Refiner, ThreadRefiner
from alexa_mcp_server.safety import crisis
from alexa_mcp_server.store import Store, make_store

INSTRUCTIONS = """\
You are connected to a personal cognitive support server for this user.

- When the user returns after a break or asks what they were doing, call what_was_i_doing.
- When the user asks you to remember something, call remember. Use kind=person for who someone is,
  kind=commitment for something they promised or need to do. For a relative time ("in 30 minutes",
  "in two hours") pass due_in_minutes; don't convert it to a clock time yourself.
- When the user asks what they told you, or what they know about something, call recall.
- When the user says something is done or handled, call close_loop with their words.
- When the user asks the time, what's next, or how long they have, call now_context.
- When the user raises a worry or comes back to a subject that is bothering them, call log_topic
  with a short description of the worry, before answering.
- When the user starts or finishes a piece of work, call start_block or end_block.
- When the user asks how long they've been at something, call check_in. If they have been at it a
  long time or ask whether they need a break, call check_hyperfocus.
- When the user says they drank water, ate, or took a break, call log_need.
- When a tool result includes suggest_reminder_minutes, offer to set an Alexa reminder for that time.
- When the user asks what a message means, call decode. If they refer to a message they just
  sent or forwarded, call decode with no message.
- When decode returns needs_work or reply_needed, make at most one offer: a reminder or a breakdown.
- After a decode, when the user asks what to say or what the sender wants, call decode_result.
- When the user asks "what needs me?" or "anything urgent?", call triage_inbox.
- When the user sounds overwhelmed by a goal ("I don't know where to start", "this is too much"),
  call decompose with the goal. Do not ask clarifying questions first.
- When the user says "done", "next", "too big", or "not now" during a task, call done_step,
  next_step, split_step, or skip_step.
- When a tool result includes fallback_hint, follow it.
- When the user lists things to remember or says "brain dump", call brain_dump. Do not ask questions.
- When the user asks to plan their day, call plan_today; pass energy if they mention it.
  If they swap a priority, call plan_today again rather than editing items one by one.
- When the user says "wrap up" or "done for today", call wrap_up.
- Speak the `speak` field from tool results in plain, literal words. Do not add idioms.
- Prefer accuracy over agreement. If the user's claim conflicts with what memory shows, say so gently.
- If a tool result has crisis: true, say only the provided message and resources. Do not redirect,
  coach, or change the subject.
- The user is in charge. If they say "I know, keep going", call override with keep_going_once.
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
_guard: crisis.Guard | None = None
_guard_loaded = False
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


def get_guard() -> crisis.Guard | None:
    """Bedrock Guardrails for the crisis precheck; ``None`` keeps the phrase list only."""
    global _guard, _guard_loaded
    if not _guard_loaded:
        _guard, _guard_loaded = make_guard(settings), True
    return _guard


def deps() -> Deps:
    global _llm
    if _llm is None:
        _llm = make_llm(settings)
    return Deps(store=get_store(), llm=_llm, embedder=get_embedder(), clock=lambda: clock(), guard=get_guard())


def get_refiner() -> Refiner:
    """Background refine jobs (spec §4): a thread pool locally, an async self-invoke on Lambda."""
    global _refiner
    if _refiner is None:
        name = settings.lambda_function_name
        _refiner = LambdaRefiner(name) if name else ThreadRefiner(deps())
    return _refiner


def warm() -> None:
    """Build clients ahead of the first request (Lambda init), so it fits the latency budget."""
    deps()
    if isinstance(refiner := get_refiner(), LambdaRefiner):
        refiner.connect()
    auth.warm(_token_verifier)


def _user() -> str:
    return auth.current_user_id(settings)


DECODE_RESULT_WAIT = 8.0
"""Seconds decode / decode_result hold the reply for Bedrock instead of the baseline / "still working"."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

Kind = Literal["fact", "person", "preference", "commitment"]


def tool(annotations: ToolAnnotations) -> Callable[[Callable[..., Any]], Any]:
    """Register an MCP tool that returns a pending crisis result (async guard hit) before anything else."""

    def register(fn: Callable[..., Any]) -> Any:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def wrapped_async(*args: Any, **kwargs: Any) -> Any:
                flagged = crisis.pending_flag(get_store(), _user(), clock())
                return flagged if flagged is not None else await fn(*args, **kwargs)

            return mcp.tool(annotations=annotations)(wrapped_async)

        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            flagged = crisis.pending_flag(get_store(), _user(), clock())
            return flagged if flagged is not None else fn(*args, **kwargs)

        return mcp.tool(annotations=annotations)(wrapped)

    return register


@mcp.tool(annotations=READ_ONLY)
def ping() -> str:
    """Health check. Returns 'pong'."""
    return "pong"


@tool(WRITE)
def remember(
    text: Annotated[str, Field(description="What to remember, in the user's words", max_length=2000)],
    kind: Annotated[Kind, Field(description="commitment = something to do; it becomes an open loop")] = "fact",
    subject: Annotated[str | None, Field(description="Person or project it's about; for person, their name")] = None,
    due_at: Annotated[
        str | None,
        Field(
            description="Local ISO 8601 in the user's time zone (call now_context if unsure); bare date = 9 AM. "
            "Commitments only"
        ),
    ] = None,
    due_in_minutes: Annotated[
        int | None,
        Field(description='Relative due time, e.g. 30 for "in 30 minutes". Use instead of due_at', ge=1, le=43200),
    ] = None,
) -> dict[str, Any]:
    """Store something the user wants kept: a fact, a person, a preference, or a commitment."""
    return memory.remember(
        get_store(),
        _user(),
        text,
        clock(),
        kind=kind,
        subject=subject,
        due_at=due_at,
        due_in_minutes=due_in_minutes,
        refiner=get_refiner(),
        guard=get_guard(),
    )


@tool(READ_ONLY)
def recall(
    query: Annotated[str, Field(description="What the user is asking about, in their words")],
    kind: Kind | None = None,
    limit: Annotated[int, Field(ge=1, le=20)] = 5,
) -> dict[str, Any]:
    """Find what the user told you before. An empty `matches` list means nothing was saved about it."""
    return memory.recall(get_store(), _user(), query, clock(), kind=kind, limit=limit, embedder=get_embedder())


@tool(READ_ONLY)
def what_was_i_doing() -> dict[str, Any]:
    """Restore context after an interruption: current work, recent memories, and open loops."""
    return memory.what_was_i_doing(get_store(), _user(), clock())


@tool(READ_ONLY)
def open_loops(limit: Annotated[int, Field(ge=1, le=20)] = 5) -> dict[str, Any]:
    """Unfinished commitments, soonest due first."""
    return memory.open_loops(get_store(), _user(), clock(), limit=limit)


@tool(WRITE)
def close_loop(text: Annotated[str, Field(description="The finished item, in the user's words")]) -> dict[str, Any]:
    """Mark an open loop done. If several match, nothing is closed and `candidates` lists them; ask which one."""
    return memory.close_loop(get_store(), _user(), text, clock(), embedder=get_embedder())


@tool(READ_ONLY)
def get_profile() -> dict[str, Any]:
    """The user's profile: name, time zone, style, thresholds, and the people they've told you about."""
    return memory.get_profile(get_store(), _user())


@tool(WRITE)
def set_preference(
    key: Annotated[str, Field(description="Dotted profile path, e.g. time.end_of_day or style.register")],
    value: Annotated[str | int | bool | list[str] | None, Field(description="New value")],
) -> dict[str, Any]:
    """Change one profile setting. The value is checked against the setting's type and range."""
    return memory.set_preference(get_store(), _user(), key, value, clock())


@tool(READ_ONLY)
def export_all() -> dict[str, Any]:
    """Every item stored for the user, as structured data."""
    return memory.export_all(get_store(), _user())


@tool(ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
def delete_all(confirm: bool = False) -> dict[str, Any]:
    """Delete everything stored for the user. Irreversible: call with confirm=true only after the user says yes."""
    return memory.delete_all(get_store(), _user(), confirm=confirm)


@tool(READ_ONLY)
def now_context() -> dict[str, Any]:
    """The time, energy zone, current work block, and next commitment with a leave-by time when travel is known."""
    return sense_of_time.now_context(get_store(), _user(), clock())


@tool(WRITE)
def start_block(
    task: Annotated[str, Field(description="The work being started, in the user's words", max_length=200)],
) -> dict[str, Any]:
    """Start timing a piece of work. A different open block is closed and reported in `auto_closed`."""
    return sense_of_time.start_block(get_store(), _user(), task, clock())


@tool(WRITE)
def end_block(
    summary: Annotated[str | None, Field(description="What got done, if the user said", max_length=500)] = None,
) -> dict[str, Any]:
    """Stop timing the current piece of work."""
    return sense_of_time.end_block(get_store(), _user(), clock(), summary=summary)


@tool(READ_ONLY)
def check_in() -> dict[str, Any]:
    """How long the current block has run, as a level: none, gentle, nudge, or hard."""
    return sense_of_time.check_in(get_store(), _user(), clock())


@tool(WRITE)
async def decode(
    message: Annotated[
        str | None,
        Field(description="The message the user received. Omit to read the newest forwarded one", max_length=4000),
    ] = None,
    sender: Annotated[str | None, Field(description="Who sent it, if the user said", max_length=200)] = None,
) -> dict[str, Any]:
    """Explain what a message most likely means, how urgent it is, and what it asks for."""
    user_id, now = _user(), clock()
    return await anyio.to_thread.run_sync(
        lambda: translator.decode(
            get_store(),
            user_id,
            now,
            message=message,
            sender=sender,
            refiner=get_refiner(),
            guard=get_guard(),
            wait=DECODE_RESULT_WAIT,
        )
    )


@tool(READ_ONLY)
async def decode_result() -> dict[str, Any]:
    """The details of the last decoded message: summary, what they want, and a suggested reply."""
    user_id = _user()  # resolve auth on the request task, before the worker thread
    return await anyio.to_thread.run_sync(
        lambda: translator.decode_result(get_store(), user_id, wait=DECODE_RESULT_WAIT)
    )


@tool(WRITE)
def triage_inbox(limit: Annotated[int, Field(ge=1, le=10)] = 3) -> dict[str, Any]:
    """What needs the user: open messages ranked by priority, then reply-by time, then age."""
    return translator.triage_inbox(get_store(), _user(), clock(), limit=limit, refiner=get_refiner(), guard=get_guard())


@tool(WRITE)
def log_topic(
    topic: Annotated[str, Field(description="The worry, in a few of the user's words", max_length=500)],
) -> dict[str, Any]:
    """Note a worry the user raised. When it keeps coming back, `detected` is true with one concrete `redirect`."""
    return guardrail.log_topic(
        get_store(), _user(), topic, clock(), embedder=get_embedder(), guard=get_guard(), refiner=get_refiner()
    )


@tool(READ_ONLY)
def check_hyperfocus() -> dict[str, Any]:
    """How long the current work has run, plus water, food, or a break not logged for too long."""
    return guardrail.check_hyperfocus(get_store(), _user(), clock())


@tool(WRITE)
def log_need(kind: Literal["water", "food", "break"]) -> dict[str, Any]:
    """Log that the user just had water, ate, or took a break."""
    return guardrail.log_need(get_store(), _user(), kind, clock())


@tool(WRITE)
def override(
    token: Annotated[
        overrides.Token,
        Field(description="snooze_15m, keep_going_once, pause_for_session, or lower_sensitivity"),
    ],
) -> dict[str, Any]:
    """Quiet guardrail prompts when the user asks. Never affects crisis resources."""
    return overrides.override(get_store(), _user(), token, clock())


@tool(WRITE)
def decompose(
    goal: Annotated[str, Field(description="The goal, in the user's words", max_length=500)],
    max_step_minutes: Annotated[int, Field(description="Longest a step may take", ge=5, le=90)] = 25,
) -> dict[str, Any]:
    """Break a goal into small steps and make it the active task. Returns step 1 at once; the rest follow."""
    return tasks.decompose(
        get_store(), _user(), goal, clock(), max_step_minutes=max_step_minutes, refiner=get_refiner(), guard=get_guard()
    )


@tool(READ_ONLY)
def next_step() -> dict[str, Any]:
    """The next undone step of the active task."""
    return tasks.next_step(get_store(), _user())


@tool(WRITE)
def done_step() -> dict[str, Any]:
    """Mark the current step done and give the next one."""
    return tasks.done_step(get_store(), _user(), clock())


@tool(WRITE)
def split_step() -> dict[str, Any]:
    """The current step is too big: replace only it with smaller steps."""
    return tasks.split_step(get_store(), _user(), refiner=get_refiner())


@tool(WRITE)
def skip_step() -> dict[str, Any]:
    """Not now: move the current step to the end of the list."""
    return tasks.skip_step(get_store(), _user())


@tool(WRITE)
def brain_dump(
    text: Annotated[str, Field(description="Everything the user listed, in their words", max_length=2000)],
) -> dict[str, Any]:
    """Save one or more things the user listed, with no follow-up questions."""
    return plan.brain_dump(get_store(), _user(), text, clock(), refiner=get_refiner(), guard=get_guard())


@tool(WRITE)
def plan_today(
    energy: Annotated[
        int | None, Field(description="The user's energy, 1 (low) to 5 (high), if they said", ge=1, le=5)
    ] = None,
) -> dict[str, Any]:
    """Pick today's few priorities from everything open. Call again if the user swaps one."""
    return plan.plan_today(get_store(), _user(), clock(), energy=energy)


@tool(WRITE)
def wrap_up() -> dict[str, Any]:
    """End the day: say what got done, move unfinished priorities to tomorrow, and stop the open block."""
    return plan.wrap_up(get_store(), _user(), clock())


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


if _auth_settings is not None:
    auth.add_root_metadata_route(mcp, _auth_settings, settings.cognito_scope)


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
