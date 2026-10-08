import json

from conftest import SEED
from mcp import Client

from alexa_mcp_server import mcp, server
from alexa_mcp_server.pillars import memory

MEMORY_TOOLS = {
    "remember",
    "recall",
    "what_was_i_doing",
    "open_loops",
    "close_loop",
    "get_profile",
    "set_preference",
    "export_all",
    "delete_all",
}


async def test_lists_tools():
    async with Client(mcp) as client:
        result = await client.list_tools()
    assert MEMORY_TOOLS | {"ping"} <= {tool.name for tool in result.tools}


async def test_every_memory_tool_returns_speak(mcp_store):
    memory.seed(mcp_store, "demo", SEED, server.clock())
    calls = {
        "remember": {"text": "Bring snacks"},
        "recall": {"query": "dentist"},
        "what_was_i_doing": {},
        "open_loops": {},
        "close_loop": {"text": "dentist"},
        "get_profile": {},
        "set_preference": {"key": "style.register", "value": "warm"},
        "export_all": {},
        "delete_all": {},
    }
    async with Client(mcp) as client:
        for name, args in calls.items():
            result = await client.call_tool(name, args)
            assert not result.is_error, name
            assert result.structured_content["speak"], name


async def test_time_tools_over_mcp(mcp_store):
    memory.seed(mcp_store, "demo", SEED, server.clock())
    calls = [
        ("now_context", {}),
        ("check_in", {}),
        ("start_block", {"task": "the slides"}),
        ("end_block", {"summary": "first draft"}),
    ]
    async with Client(mcp) as client:
        assert {name for name, _ in calls} <= {tool.name for tool in (await client.list_tools()).tools}
        for name, args in calls:
            result = await client.call_tool(name, args)
            assert not result.is_error, name
            assert result.structured_content["speak"], name
        assert (await client.call_tool("end_block", {})).structured_content["error"]["code"] == "NOT_FOUND"


async def test_translator_tools_over_mcp(mcp_store):
    memory.seed(mcp_store, "demo", SEED, server.clock())
    async with Client(mcp) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert {"decode", "decode_result", "triage_inbox"} <= names
        decoded = await client.call_tool("decode", {"message": "Can you send the deck today? Thanks, Priya"})
        assert decoded.structured_content["sender_source"] == "signature"
        assert decoded.structured_content["refine"] == "failed"  # no LLM configured in tests
        detail = await client.call_tool("decode_result", {})
        assert detail.structured_content["speak"].startswith("I couldn't get more detail")
        triage = await client.call_tool("triage_inbox", {})
        assert triage.structured_content["items"][0]["sender"] == "Priya"
        empty = await client.call_tool("decode", {})
        assert empty.structured_content["error"]["code"] == "NOT_FOUND"
        too_long = await client.call_tool("decode", {"message": "x" * 4001})
        assert too_long.is_error


async def test_remember_then_recall_over_mcp(mcp_store):
    async with Client(mcp) as client:
        await client.call_tool("remember", {"text": "Jordan owns the venue booking", "subject": "Jordan"})
        result = await client.call_tool("recall", {"query": "venue"})
    assert result.structured_content["matches"][0]["text"] == "Jordan owns the venue booking"


async def test_invalid_kind_rejected(mcp_store):
    async with Client(mcp) as client:
        result = await client.call_tool("remember", {"text": "x", "kind": "secret"})
    assert result.is_error


async def test_profile_resource(mcp_store):
    memory.seed(mcp_store, "demo", SEED, server.clock())
    async with Client(mcp) as client:
        result = await client.read_resource("profile://me")
    profile = json.loads(result.contents[0].text)
    assert profile["display_name"] == "Sam"
    assert "speak" not in profile
