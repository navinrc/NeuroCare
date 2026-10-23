#!/usr/bin/env bash
# Render the demo video end to end: audio clips → fresh seed → live take → cut + mix.
#   DEMO_SUB=<cognito sub> DEMO_EMAIL=<email> DEMO_PASSWORD_FILE=<file> scripts/video/render.sh
# Output: scripts/video/out/neurocare-demo.mp4
set -euo pipefail
cd "$(dirname "$0")/../.."
export AWS_PROFILE="${AWS_PROFILE:-neurocare-deployer}" AWS_REGION=us-east-1
uv run python scripts/video/tts.py prepare
STORE=dynamo DEMO_USER_ID="$DEMO_SUB" uv run alexa-mcp-seed --reset
(cd scripts/video && [ -d node_modules ] || npm install --silent) && (cd scripts/video && rm -rf out/raw out/sim.webm && node record.mjs)
uv run python scripts/video/assemble.py
