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

## Environment

| Variable | Default | Notes |
|---|---|---|
| `HOST`, `PORT` | `127.0.0.1`, `8000` | |
| `STORE`, `SQLITE_PATH` | `sqlite`, `.data/neurocare.sqlite3` | |
| `ALLOW_STATIC_TOKEN`, `AUTH_TOKEN` | off | Local dev / Inspector bearer token |
| `DEMO_USER_ID` | `demo` | User served when auth is off |
| `LLM_PROVIDER` | `off` | `bedrock` turns on the LLM refine and the embedding tier; `off` = deterministic baselines only |
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Converse model / inference profile |
| `BEDROCK_EMBED_MODEL_ID` | `amazon.titan-embed-text-v2:0` | |
| `AWS_REGION` | `us-east-1` | Credentials come from the usual AWS chain (`AWS_PROFILE`, …) |

## Forwarding a message (`POST /inbox`)

```bash
uv run alexa-mcp-inbox-token        # prints a personal token once (Telegram /token does this in phase 6b)
curl -X POST http://127.0.0.1:8000/inbox -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"text": "Per my last email...", "sender": "Priya"}'
# then: decode() with no message, or triage_inbox()
```

## Development
```bash
uv run pytest
BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin uv run pytest -m live -s   # one real Bedrock call
scripts/prove.sh scripts/smoke/phase3.yaml                              # live HTTP proof (docs/verify/)
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
  pillars/sense_of_time.py  # now_context, work blocks, check_in
  pillars/translator.py     # decode, decode_result, triage_inbox, inbox items
  pillars/inbox.py          # personal inbox tokens for POST /inbox
  llm/               # LLM + Embedder protocols, Bedrock clients, fakes for tests
  refine.py          # fast-first background refine jobs
  semantic.py        # embedding tier (recall, close_loop; rumination in phase 4)
  matching.py        # tiered recall: exact → alias → fuzzy → embedding
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
