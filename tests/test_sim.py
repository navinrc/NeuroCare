"""Phase 6a: the Alexa simulator (spec §5.9) against the in-process MCP server."""

import json
import urllib.parse
from typing import Any

import pytest
from conftest import NOW
from starlette.testclient import TestClient

from alexa_mcp_server import server
from alexa_sim import oauth
from alexa_sim.agent import GIVE_UP, LINK_PROMPT, MAX_TOOL_ROUNDS, connect, run_turn
from alexa_sim.app import COOKIE, Sim, build_app
from alexa_sim.config import SimSettings
from alexa_sim.sessions import HISTORY_TURNS, MemorySessions, Session

T = NOW.timestamp()
LINKED = {"access_token": "acc", "refresh_token": "ref-SECRET", "expires_at": T + 3600}


class FakeModel:
    """Scripted Converse replies in order (the last repeats); a reply may be ``fn(messages, tools)``."""

    def __init__(self, *replies: Any):
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def converse(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append({"system": system, "messages": json.loads(json.dumps(messages)), "tools": tools})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return reply(messages, tools) if callable(reply) else reply


def say(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": [{"text": text}]}


def use(name: str, arguments: dict | None = None, id_: str = "t1") -> dict[str, Any]:
    return {"role": "assistant", "content": [{"toolUse": {"toolUseId": id_, "name": name, "input": arguments or {}}}]}


def open_in_process():
    return connect(server.mcp, "unused")


async def turn(text: str, session: Session, model: FakeModel, **kw: Any):
    return await run_turn(text, session, model=model, open_tools=open_in_process, now=T, tz="America/New_York", **kw)


async def test_tools_and_instructions_come_from_the_server(seeded, mcp_store):
    model = FakeModel(say("Hi."))
    await turn("hello", Session(id="s"), model)
    call = model.calls[0]
    names = {t["toolSpec"]["name"] for t in call["tools"]}
    assert len(names) == 30 and {"what_was_i_doing", "decompose", "set_reminder"} <= names  # 29 + set_reminder
    assert server.INSTRUCTIONS.splitlines()[0] in call["system"]
    assert "America/New_York" in call["system"]


async def test_tool_call_result_is_fed_back(seeded, mcp_store):
    model = FakeModel(
        use("what_was_i_doing"),
        lambda messages, tools: say(messages[-1]["content"][0]["toolResult"]["content"][0]["json"]["speak"]),
    )
    session = Session(id="s")
    result = await turn("what was I doing?", session, model)
    (call,) = result.tool_calls
    assert call["name"] == "what_was_i_doing" and "speak" in call["result"] and call["ms"] >= 0
    assert result.reply == call["result"]["speak"]
    assert session.history[-2:] == [
        {"role": "user", "text": "what was I doing?"},
        {"role": "assistant", "text": result.reply},
    ]


async def test_crisis_result_is_spoken_verbatim_without_the_model(seeded, mcp_store):
    model = FakeModel(use("remember", {"text": "I want to kill myself"}), say("SHOULD NOT BE SPOKEN"))
    result = await turn("remember that I want to kill myself", Session(id="s"), model)
    assert result.crisis and result.crisis["crisis"] is True
    assert result.reply == result.crisis["speak"] and "988" in result.reply
    assert len(model.calls) == 1  # no second model call to rephrase it


async def test_tool_rounds_are_capped(seeded, mcp_store):
    model = FakeModel(use("ping"))
    result = await turn("loop forever", Session(id="s"), model)
    assert result.reply == GIVE_UP
    assert len(result.tool_calls) == MAX_TOOL_ROUNDS and len(model.calls) == MAX_TOOL_ROUNDS + 1


async def test_unlinked_user_gets_the_link_prompt():
    def refuse():
        raise oauth.LinkRequired()

    model = FakeModel(say("never"))
    result = await run_turn("what was I doing?", Session(id="s"), model=model, open_tools=refuse, now=T)
    assert result.link_required and result.reply == LINK_PROMPT and model.calls == []


async def test_set_reminder_fires_at_the_time(seeded, mcp_store):
    model = FakeModel(use("set_reminder", {"minutes": 30, "text": "drink water"}), say("Okay."))
    session = Session(id="s")
    result = await turn("remind me in 30 minutes to drink water", session, model)
    (reminder,) = result.reminders_set
    assert reminder["due_at"] == T + 1800 and result.tool_calls[0]["result"]["speak"].startswith(
        "Okay, I'll remind you at"
    )
    assert session.due_reminders(T + 1799) == []
    assert [r["text"] for r in session.due_reminders(T + 1800)] == ["drink water"]
    again = await turn(
        "yes please", session, FakeModel(use("set_reminder", {"minutes": 30, "text": "Drink water"}), say("Ok."))
    )
    assert again.reminders_set == [] and again.tool_calls[0]["result"]["already_set"] is True
    assert len(session.reminders) == 1
    bad = await turn("remind me", session, FakeModel(use("set_reminder", {"minutes": 0, "text": ""}), say("Hmm.")))
    assert "error" in bad.tool_calls[0]["result"]


async def test_history_is_capped(seeded, mcp_store):
    session = Session(id="s")
    for i in range(HISTORY_TURNS + 3):
        await turn(f"turn {i}", session, FakeModel(say(f"reply {i}")))
    assert len(session.history) == 2 * HISTORY_TURNS and session.history[0]["text"] == "turn 3"


# --- OAuth ----------------------------------------------------------------------------------------

SETTINGS = SimSettings(
    cognito_domain="auth.example.com", client_id="cid", client_secret="sec", public_url="https://sim.example.com"
)


class FakeToken:
    def __init__(self, *replies: tuple[int, dict]):
        self.replies, self.calls = list(replies), []

    def __call__(self, url: str, form: dict[str, str], basic: str) -> tuple[int, dict]:
        self.calls.append(form)
        return self.replies.pop(0)


def test_start_link_sends_pkce_s256_and_resource():
    session = Session(id="s")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(oauth.start_link(session, SETTINGS)).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [oauth.challenge_for(session.oauth["verifier"])]
    assert query["state"] == [session.oauth["state"]]
    assert query["redirect_uri"] == ["https://sim.example.com/sim/callback"]
    assert query["scope"] == ["openid email neurocare/tools"]


def test_callback_rejects_wrong_or_reused_state():
    session = Session(id="s")
    oauth.start_link(session, SETTINGS)
    with pytest.raises(oauth.OAuthError):
        oauth.finish_link(session, SETTINGS, "code", "wrong", T, FakeToken())
    assert session.oauth == {}  # a failed attempt burns the state too

    oauth.start_link(session, SETTINGS)
    state, verifier = session.oauth["state"], session.oauth["verifier"]
    post = FakeToken((200, {"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}))
    oauth.finish_link(session, SETTINGS, "code", state, T, post)
    assert post.calls[0]["code_verifier"] == verifier and session.tokens["refresh_token"] == "r1"
    with pytest.raises(oauth.OAuthError):
        oauth.finish_link(session, SETTINGS, "code", state, T, FakeToken())  # single use


def test_expired_access_token_is_refreshed():
    session = Session(id="s", tokens={"access_token": "old", "refresh_token": "r1", "expires_at": T + 30})
    post = FakeToken((200, {"access_token": "new", "expires_in": 3600}))
    assert oauth.access_token(session, SETTINGS, T, post) == "new"
    assert post.calls[0]["grant_type"] == "refresh_token" and session.tokens["refresh_token"] == "r1"
    assert oauth.access_token(session, SETTINGS, T, FakeToken()) == "new"  # fresh: no call


def test_failed_refresh_requires_linking_again():
    session = Session(id="s", tokens={"access_token": "old", "refresh_token": "r1", "expires_at": T - 1})
    with pytest.raises(oauth.LinkRequired):
        oauth.access_token(session, SETTINGS, T, FakeToken((400, {"error": "invalid_grant"})))
    assert session.tokens == {}


# --- web app --------------------------------------------------------------------------------------


@pytest.fixture
def sim(seeded, mcp_store):
    return Sim(
        settings=SETTINGS, store=MemorySessions(), model=FakeModel(say("Okay.")), mcp_target=server.mcp, clock=lambda: T
    )


def test_app_link_flow_and_turn(sim):
    client = TestClient(build_app(sim), base_url="https://sim.example.com")
    state = client.get("/sim/state")
    assert state.json()["linked"] is False and state.json()["can_link"] is True
    cookie = state.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie

    unlinked = client.post("/sim/turn", json={"text": "what was I doing?", "tz": "America/New_York"}).json()
    assert unlinked["link_required"] is True

    link = client.get("/sim/link", follow_redirects=False)
    assert link.status_code == 302 and link.headers["location"].startswith("https://auth.example.com/oauth2/authorize?")
    state_param = urllib.parse.parse_qs(urllib.parse.urlparse(link.headers["location"]).query)["state"][0]

    sim.post = FakeToken((200, {"access_token": "acc", "refresh_token": "ref-SECRET", "expires_in": 3600}))
    bad = client.get("/sim/callback", params={"code": "c", "state": "nope"}, follow_redirects=False)
    assert bad.headers["location"] == "/?link_error=1"
    client.get("/sim/link", follow_redirects=False)
    state_param = sim.store.get(client.cookies[COOKIE]).oauth["state"]
    ok = client.get("/sim/callback", params={"code": "c", "state": state_param}, follow_redirects=False)
    assert ok.headers["location"] == "/?linked=1"
    assert client.get("/sim/state").json()["linked"] is True

    sim.model = FakeModel(use("what_was_i_doing"), say("You were working on the budget email."))
    reply = client.post("/sim/turn", json={"text": "what was I doing?", "tz": "America/New_York"})
    body = reply.json()
    assert (
        body["reply"] == "You were working on the budget email." and body["tool_calls"][0]["name"] == "what_was_i_doing"
    )
    for response in (state, reply, client.get("/sim/state")):
        assert "ref-SECRET" not in response.text  # the refresh token never reaches the browser

    assert client.post("/sim/unlink").json() == {"linked": False}
    assert client.get("/sim/state").json()["linked"] is False


def test_app_reminder_due_and_ack(sim):
    client = TestClient(build_app(sim), base_url="https://sim.example.com")
    client.get("/sim/state")
    session = sim.store.get(client.cookies[COOKIE])
    session.tokens = dict(LINKED)
    session.reminders = [{"id": "r1", "text": "drink water", "due_at": T - 1, "acked": False}]
    sim.store.save(session)
    assert [r["id"] for r in client.get("/sim/state").json()["due"]] == ["r1"]
    client.post("/sim/reminders/r1/ack")
    assert client.get("/sim/state").json()["due"] == []


def test_app_rejects_bad_turn_input(sim):
    client = TestClient(build_app(sim), base_url="https://sim.example.com")
    assert client.post("/sim/turn", json={"text": ""}).status_code == 400
    assert client.post("/sim/turn", json={"text": "x" * 1001}).status_code == 400
    assert client.post("/sim/turn", content=b"not json").status_code == 400


def test_page_is_served(sim):
    page = TestClient(build_app(sim)).get("/")
    assert page.status_code == 200 and "Alexa+ simulator" in page.text


def test_simulator_handler_never_starts_the_server():
    """In the simulator Lambda, importing the shared adapter must not run the server's init (FINDINGS #60)."""
    import subprocess
    import sys

    code = (
        "import os, sys; os.environ['AWS_LAMBDA_FUNCTION_NAME']='x'; os.environ['SIM_PUBLIC_URL']='https://s';"
        "os.environ['SIM_MCP_URL']='https://m/mcp'; import alexa_mcp_server.asgi_lambda;"
        "print('alexa_mcp_server.server' in sys.modules, 'alexa_mcp_server.lambda_handler' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.split() == ["False", "False"]
    source = open("src/alexa_sim/lambda_handler.py").read()
    assert "alexa_mcp_server.lambda_handler" not in source and "alexa_mcp_server.asgi_lambda" in source
