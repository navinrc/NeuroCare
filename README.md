# NeuroCare

A cognitive substrate for Alexa+: an MCP server that gives neurodivergent people persistent memory, a sense of time, a translator for ambiguous messages, task breakdown, and guardrails against rumination and hyperfocus.

See the [spec](docs/spec.md) for design, tools, and AWS architecture, and
[AWS setup](docs/aws-setup.md) for account, Bedrock, and agent-toolkit configuration.

Built for the [Amazon Developer Hackathon 2026](https://amazonappdev2026.devpost.com/) — **Alexa+ track**.

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
