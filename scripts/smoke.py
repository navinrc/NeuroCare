"""Call tools on a running server over Streamable HTTP and print each result (verification proofs).

    uv run python scripts/smoke.py scripts/smoke/phase2.yaml [--url URL] [--token TOKEN]

The YAML file is a list of steps: ``{tool: name, args: {...}}``, ``{list_tools: true}``, or
``{inbox: {text, sender?}}`` (POST /inbox with the same bearer token).
Output is Markdown, so it can be pasted into docs/verify/.
"""

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


async def run(steps: list[dict], url: str, token: str | None) -> int:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    failures = 0
    transport = streamable_http_client(url, http_client=create_mcp_http_client(headers=headers))
    async with Client(transport) as client:
        for n, step in enumerate(steps, 1):
            if "inbox" in step:
                status, reply = post_inbox(url, token, step["inbox"])
                ok = status == step.get("status", 201)
                failures += not ok
                print(f"### {n}. `POST /inbox {json.dumps(step['inbox'])}` → HTTP {status} {'✅' if ok else '❌'}\n")
                print("```json\n" + json.dumps(reply, indent=2) + "\n```\n")
                continue
            if step.get("list_tools"):
                tools = sorted(t.name for t in (await client.list_tools()).tools)
                print(f"### {n}. tools/list\n\n{len(tools)} tools: {', '.join(tools)}\n")
                continue
            name, args = step["tool"], step.get("args") or {}
            started = time.perf_counter()
            result = await client.call_tool(name, args)
            ms = (time.perf_counter() - started) * 1000
            body = result.structured_content
            if body is None:
                body = [getattr(c, "text", str(c)) for c in result.content]
            ok = not result.is_error and isinstance(body, dict) and "speak" in body
            expect = step.get("expect") or {}
            for key, want in expect.items():
                got = body.get(key) if isinstance(body, dict) else None
                if key == "error_code":
                    got = (body.get("error") or {}).get("code") if isinstance(body, dict) else None
                if got != want:
                    ok = False
                    print(f"> EXPECT FAILED: {key} = {got!r}, wanted {want!r}\n")
            failures += not ok
            arg_text = json.dumps(args) if args else ""
            print(f"### {n}. `{name}({arg_text})` — {ms:.0f} ms {'✅' if ok else '❌'}\n")
            print("```json\n" + json.dumps(body, indent=2, ensure_ascii=False) + "\n```\n")
    return failures


def post_inbox(mcp_url: str, token: str | None, body: dict) -> tuple[int, dict]:
    url = mcp_url.rsplit("/mcp", 1)[0] + "/inbox"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("steps")
    parser.add_argument("--url", default=os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp"))
    parser.add_argument("--token", default=os.getenv("AUTH_TOKEN"))
    args = parser.parse_args()
    steps = yaml.safe_load(Path(args.steps).read_text())
    failures = asyncio.run(run(steps, args.url, args.token))
    print(f"**{len(steps)} steps, {failures} failed**")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
