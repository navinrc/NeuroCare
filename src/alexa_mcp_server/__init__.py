"""Alexa+ MCP server (Streamable HTTP).

``main`` and ``mcp`` load lazily: importing a submodule (``alexa_mcp_server.lambda_handler``) must
not import ``server`` yet, because ``server`` reads its settings at import time and the Lambda
handler sets ``PUBLIC_BASE_URL`` first.
"""

from typing import Any

__all__ = ["main", "mcp"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from alexa_mcp_server import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
