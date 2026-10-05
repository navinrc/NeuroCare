# NeuroCare

A cognitive substrate for Alexa+: an MCP server that gives neurodivergent people persistent memory, a sense of time, a translator for ambiguous messages, task breakdown, a low-overwhelm daily plan, and guardrails against rumination and hyperfocus. An optional Telegram companion bot handles forwarded messages, a pinned daily view, and opt-in nudges.

See the [spec](docs/spec.md) for design, tools, and AWS architecture, and
[AWS setup](docs/aws-setup.md) for account, Bedrock, Telegram, and agent-toolkit configuration.

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
uv run alexa-mcp-seed --reset # load synthetic demo data (profile_seed.yaml) into .data/
uv run alexa-mcp-server       # http://127.0.0.1:8000/mcp
```

Without auth env vars every request is served as `DEMO_USER_ID` (default `demo`). To require a
bearer token locally:
```bash
ALLOW_STATIC_TOKEN=true AUTH_TOKEN=devtoken uv run alexa-mcp-server
```

Inspect with the MCP Inspector:
```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP, URL: http://127.0.0.1:8000/mcp
# With a static token: add header  Authorization: Bearer devtoken
# Try: what_was_i_doing, recall("my boss"), open_loops
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
  server.py          # MCPServer instance, thin tool layer, entrypoint
  config.py          # env settings
  auth.py            # static dev token (Cognito JWT in phase 6)
  store/             # Store interface + SQLite backend
  pillars/memory.py  # memory tools, profile, seed loader
  profile.py         # profile schema, defaults, validation
  matching.py        # tiered recall: exact → alias → fuzzy
  speech.py          # short spoken-text helpers
  seed.py            # alexa-mcp-seed CLI
profile_seed.yaml    # synthetic demo data
tests/               # pytest; in-process MCP client + pillar tests
```

## Resources
- Hackathon resources: https://amazonappdev2026.devpost.com/resources
- Agent Skills: https://apps.extensions.modelcontextprotocol.io/api/#build-with-agent-skills
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Amazon Devices Builder Tools (MCP): https://developer.amazon.com/docs/vega/0.24/mcp-server
