"""MCP server entrypoint.

Exposes tools over the Streamable HTTP transport at ``http://<host>:<port>/mcp``.
"""

import os

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="alexa-mcp-server",
    instructions="Tools for an Alexa+ experience.",
)


@mcp.tool()
def ping() -> str:
    """Health check. Returns 'pong'."""
    return "pong"


@mcp.tool()
def greet(name: str) -> str:
    """Greet a user by name."""
    return f"Hello, {name}! Welcome to Alexa+."


def main() -> None:
    mcp.run(
        transport="streamable-http",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
