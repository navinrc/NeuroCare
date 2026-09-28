# alexa-mcp-server

MCP server for the [Amazon Developer Hackathon 2026](https://amazonappdev2026.devpost.com/) — **Alexa+ track**.

Implements a [Model Context Protocol](https://modelcontextprotocol.io) server over the
[Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#streamable-http),
per the track requirements.

## Requirements
- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

## Quickstart
```bash
uv sync
cp .env.example .env          # optional: HOST / PORT
uv run alexa-mcp-server       # http://127.0.0.1:8000/mcp
```

Inspect with the MCP Inspector:
```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP, URL: http://127.0.0.1:8000/mcp
```

## Development
```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Project layout
```
src/alexa_mcp_server/
  server.py      # MCPServer instance, tools, entrypoint
tests/
  test_server.py # in-process client tests
```

## Resources
- Hackathon resources: https://amazonappdev2026.devpost.com/resources
- Agent Skills: https://apps.extensions.modelcontextprotocol.io/api/#build-with-agent-skills
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Amazon Devices Builder Tools (MCP): https://developer.amazon.com/docs/vega/0.24/mcp-server
