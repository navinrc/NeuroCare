# CLAUDE.md

MCP server for the Amazon Developer Hackathon 2026 (Alexa+ track). Built on the official
`mcp` Python SDK **v2** — `FastMCP` is now `mcp.server.mcpserver.MCPServer`; don't use v1 imports.

## Commands
- `uv sync` — install deps
- `uv run alexa-mcp-seed --reset` — load `profile_seed.yaml` into the local SQLite store
- `uv run alexa-mcp-server` — serve Streamable HTTP at `http://127.0.0.1:8000/mcp`
- `uv run pytest` — tests (in-process via `mcp.Client(mcp)`)
- `uv run ruff check . && uv run ruff format .` — lint/format

## Layout
- `src/alexa_mcp_server/server.py` — server instance + thin tool layer
- `src/alexa_mcp_server/pillars/` — pillar logic as plain functions `(store, user_id, ..., now)`
- `src/alexa_mcp_server/store/` — Store interface; SQLite backend (DynamoDB in phase 6)
- `docs/spec.md` — source of truth; build phases in §11
- `tests/` — pytest (asyncio auto mode)

## Rules
- Transport must stay Streamable HTTP (hackathon requirement).
- Never commit `.env` or secrets.
- No Claude/Anthropic attribution in commit messages.
