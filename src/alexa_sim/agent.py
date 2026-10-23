"""The simulator's turn loop: its own model with tool use, the server's tools over MCP (spec §5.9).

One user utterance → Converse with the server's ``instructions`` as system prompt and the server's
``tools/list`` as tools (plus a local ``set_reminder``) → each tool call goes to the server over
Streamable HTTP with the user's bearer token → results fed back until the model answers in text.
"""

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import anyio
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from alexa_sim.oauth import LinkRequired
from alexa_sim.sessions import Session

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
GIVE_UP = "Sorry, I couldn't finish that."
LINK_PROMPT = "To use NeuroCare, link your account. Tap Link NeuroCare on the screen."
ERROR_REPLY = "Sorry, something went wrong reaching NeuroCare."

PERSONA = """\
You are Alexa, the voice assistant on an Echo Show, with the NeuroCare add-on enabled.
Your replies are spoken aloud: one to three short, plain sentences. No markdown, lists, or emoji.
Call NeuroCare tools whenever the instructions below say to; don't answer from your own memory.
Say a tool's `speak` text plainly; you may add a short follow-up offer the instructions ask for.
To set an Alexa reminder, call set_reminder only after the user agrees.
It is now {now} ({tz}).

NeuroCare server instructions:
{instructions}"""

SET_REMINDER = {
    "toolSpec": {
        "name": "set_reminder",
        "description": "Set a native Alexa reminder that chimes on this device. Only after the user agrees.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "minimum": 1, "maximum": 1440, "description": "Minutes from now"},
                    "text": {"type": "string", "maxLength": 200, "description": "What to remind about"},
                },
                "required": ["minutes", "text"],
            }
        },
    }
}


class Model(Protocol):
    def converse(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        """One Converse call; returns the assistant message ``{"role": "assistant", "content": [...]}``."""
        ...


class BedrockModel:
    def __init__(self, model_id: str, region: str):
        import boto3
        from botocore.config import Config

        config = Config(connect_timeout=3, read_timeout=20, retries={"max_attempts": 2})
        self._client = boto3.client("bedrock-runtime", region_name=region, config=config)
        self._model_id = model_id

    def converse(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        response = self._client.converse(
            modelId=self._model_id,
            system=[{"text": system}],
            messages=messages,
            toolConfig={"tools": tools},
            inferenceConfig={"maxTokens": 400, "temperature": 0.2},
        )
        return response["output"]["message"]


@dataclass
class TurnResult:
    reply: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    """``{"name", "arguments", "result", "ms"}`` per call, in order (dev panel)."""
    model_ms: int = 0
    link_required: bool = False
    crisis: dict[str, Any] | None = None
    reminders_set: list[dict[str, Any]] = field(default_factory=list)


class Tools(Protocol):
    instructions: str
    specs: list[dict[str, Any]]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class McpTools:
    """The server's tools over one MCP client connection."""

    def __init__(self, client: Client, instructions: str, specs: list[dict[str, Any]], statuses: list[int]):
        self._client, self.instructions, self.specs, self._statuses = client, instructions, specs, statuses

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self._client.call_tool(name, arguments)
        except Exception:
            if 401 in self._statuses or 403 in self._statuses:  # token revoked or expired mid-session
                raise LinkRequired() from None
            raise
        if isinstance(result.structured_content, dict):
            return result.structured_content
        text = "".join(getattr(block, "text", "") for block in result.content)
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {"result": value}
        except ValueError:
            return {"error": {"code": "TOOL_ERROR", "message": text[:500]}} if result.is_error else {"text": text}


def tool_spec(tool: Any) -> dict[str, Any]:
    return {
        "toolSpec": {
            "name": tool.name,
            "description": (tool.description or tool.name)[:1000],
            "inputSchema": {"json": tool.input_schema or {"type": "object", "properties": {}}},
        }
    }


@asynccontextmanager
async def connect(target: Any, token: str) -> AsyncIterator[McpTools]:
    """Open an MCP session as the user. ``target`` is the server URL, or an in-process server (tests).

    A 401 from the server raises ``LinkRequired``, the way Alexa+ starts account linking.
    """
    statuses: list[int] = []
    if isinstance(target, str):
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})

        async def record(response: Any) -> None:
            statuses.append(response.status_code)

        http.event_hooks["response"].append(record)
        server: Any = streamable_http_client(target, http_client=http)
    else:
        server = target
    try:
        async with Client(server) as client:
            listed = await client.list_tools()
            yield McpTools(client, client.instructions or "", [tool_spec(t) for t in listed.tools], statuses)
    except BaseException:
        if 401 in statuses or 403 in statuses:
            raise LinkRequired() from None
        raise


def _messages(history: list[dict[str, str]], text: str) -> list[dict[str, Any]]:
    turns = [{"role": h["role"], "content": [{"text": h["text"]}]} for h in history if h.get("text")]
    return [*turns, {"role": "user", "content": [{"text": text}]}]


def _set_reminder(session: Session, arguments: dict[str, Any], now: float, tz: ZoneInfo) -> dict[str, Any]:
    try:
        minutes = int(arguments.get("minutes", 0))
    except (TypeError, ValueError):
        minutes = 0
    text = str(arguments.get("text", "")).strip()[:200]
    if not 1 <= minutes <= 1440 or not text:
        return {"error": {"code": "INVALID_ARGUMENT", "message": "minutes 1-1440 and text are required"}}
    due_at = now + minutes * 60
    same = next(
        (
            r
            for r in session.reminders
            if not r.get("acked") and r["text"].lower() == text.lower() and abs(r["due_at"] - due_at) <= 120
        ),
        None,
    )
    if same is not None:  # "yes please" after the model already set it: don't set it twice
        at = datetime.fromtimestamp(same["due_at"], tz).strftime("%-I:%M %p")
        return {"ok": True, "already_set": True, "due_at": at, "speak": f"That reminder is already set for {at}."}
    reminder = {"id": uuid.uuid4().hex[:12], "text": text, "due_at": due_at, "acked": False}
    session.reminders = [r for r in session.reminders if not r.get("acked")][-19:] + [reminder]
    at = datetime.fromtimestamp(reminder["due_at"], tz).strftime("%-I:%M %p")
    return {"ok": True, "due_at": at, "speak": f"Okay, I'll remind you at {at}."}


async def run_turn(
    text: str,
    session: Session,
    *,
    model: Model,
    open_tools: Callable[[], Any],
    now: float,
    tz: str = "UTC",
) -> TurnResult:
    """Answer one utterance. ``open_tools()`` returns the ``connect(...)`` context manager."""
    zone = _zone(tz)
    turn = TurnResult(reply="")
    try:
        async with open_tools() as tools:
            system = PERSONA.format(
                now=datetime.fromtimestamp(now, zone).strftime("%A %B %-d, %-I:%M %p"),
                tz=zone.key,
                instructions=tools.instructions,
            )
            specs = [*tools.specs, SET_REMINDER]
            messages = _messages(session.history, text)
            for tool_round in range(MAX_TOOL_ROUNDS + 1):
                started = time.perf_counter()
                message = await anyio.to_thread.run_sync(lambda: model.converse(system, messages, specs))
                turn.model_ms += round((time.perf_counter() - started) * 1000)
                messages.append(message)
                uses = [block["toolUse"] for block in message.get("content", []) if "toolUse" in block]
                if not uses:
                    turn.reply = " ".join(b["text"] for b in message.get("content", []) if "text" in b).strip()
                    break
                if tool_round == MAX_TOOL_ROUNDS:  # the model still wants tools after the last round
                    turn.reply = GIVE_UP
                    break
                results = []
                for use in uses:
                    result, ms = await _call(tools, session, use, now, zone, turn)
                    turn.tool_calls.append(
                        {"name": use["name"], "arguments": use.get("input", {}), "result": result, "ms": ms}
                    )
                    if result.get("crisis") is True:  # say only the provided message (spec §6)
                        turn.crisis = result
                        turn.reply = result.get("speak", "")
                        return turn
                    results.append({"toolResult": {"toolUseId": use["toolUseId"], "content": [{"json": result}]}})
                messages.append({"role": "user", "content": results})
    except LinkRequired:
        turn.link_required, turn.reply = True, LINK_PROMPT
        return turn
    except Exception:
        log.exception("turn failed")
        turn.reply = ERROR_REPLY
        return turn
    turn.reply = turn.reply or GIVE_UP
    session.remember_turn(text, turn.reply)
    return turn


async def _call(
    tools: Tools, session: Session, use: dict[str, Any], now: float, zone: ZoneInfo, turn: TurnResult
) -> tuple[dict[str, Any], int]:
    started = time.perf_counter()
    arguments = use.get("input") or {}
    if use["name"] == "set_reminder":
        result = _set_reminder(session, arguments, now, zone)
        if result.get("ok") and not result.get("already_set"):
            turn.reminders_set.append(session.reminders[-1])
    else:
        try:
            result = await tools.call(use["name"], arguments)
        except LinkRequired:
            raise
        except Exception as error:  # a bad call is reported back to the model, as Alexa+ would
            result = {"error": {"code": "TOOL_ERROR", "message": str(error)[:300]}}
    return result, round((time.perf_counter() - started) * 1000)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")
