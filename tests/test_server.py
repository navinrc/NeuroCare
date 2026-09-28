from mcp import Client

from alexa_mcp_server import mcp


async def test_lists_tools():
    async with Client(mcp) as client:
        result = await client.list_tools()
    names = {tool.name for tool in result.tools}
    assert {"ping", "greet"} <= names


async def test_greet():
    async with Client(mcp) as client:
        result = await client.call_tool("greet", {"name": "Ada"})
    assert "Hello, Ada!" in result.content[0].text
