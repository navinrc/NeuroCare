#!/usr/bin/env bash
# Live proof for one phase: fresh seeded DB → server with a static token → smoke steps → stop.
#   scripts/prove.sh scripts/smoke/phase2.yaml [out.md]
# Uses its own SQLite file and port, so your .data/ database is untouched.
set -euo pipefail

steps="$1"
out="${2:-/dev/stdout}"
work="$(mktemp -d)"
export SQLITE_PATH="$work/proof.sqlite3"
export PORT="${PROOF_PORT:-8765}"
export ALLOW_STATIC_TOKEN=true
export AUTH_TOKEN=prooftoken

uv run alexa-mcp-seed --reset >/dev/null
uv run alexa-mcp-server >"$work/server.log" 2>&1 &
server=$!
trap 'kill $server 2>/dev/null; wait $server 2>/dev/null || true; rm -rf "$work"' EXIT

for _ in $(seq 1 50); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/mcp" && break
  sleep 0.2
done

unauth=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/mcp")
{
  echo "_Run at $(date '+%Y-%m-%d %H:%M %Z') against http://127.0.0.1:$PORT/mcp (fresh seed)._"
  echo
  echo "Unauthenticated POST /mcp → HTTP $unauth (expect 401)"
  echo
} >"$out"
uv run python scripts/smoke.py "$steps" --url "http://127.0.0.1:$PORT/mcp" --token "$AUTH_TOKEN" >>"$out"
