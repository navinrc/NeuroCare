"""Round-trip latency of the Alexa-path tools against a deployed server (spec §11 phase 6: < 500 ms warm).

    TOKEN=<cognito access token> uv run python scripts/latency.py https://<id>.lambda-url.us-east-1.on.aws/mcp

Each call is one stateless JSON-RPC POST, as Alexa+ makes it. The first round warms the Lambda and
is not counted. Read-only tools only, so the demo data is not changed. ``decode`` is left out: it
waits for the Bedrock refine on purpose (FINDINGS, phase 3).
"""

import argparse
import json
import os
import statistics
import time
import urllib.request

TOOLS: list[tuple[str, dict]] = [
    ("ping", {}),
    ("what_was_i_doing", {}),
    ("now_context", {}),
    ("check_in", {}),
    ("open_loops", {}),
    ("recall", {"query": "Priya"}),
    ("get_profile", {}),
    ("next_step", {}),
    ("check_hyperfocus", {}),
]
BUDGET_MS = 500


def call(url: str, token: str, name: str, args: dict) -> tuple[float, int]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
    request = urllib.request.Request(
        url,
        data=body.encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 — URL given by the operator
        response.read()
        status = response.status
    return (time.perf_counter() - start) * 1000, status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url")
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    token = os.environ["TOKEN"]

    for name, arguments in TOOLS:  # warm-up round
        call(args.url, token, name, arguments)

    print(f"| Tool | p50 ms | max ms | ≤ {BUDGET_MS} ms |\n|---|---|---|---|")
    worst = 0.0
    for name, arguments in TOOLS:
        samples = []
        for _ in range(args.rounds):
            ms, status = call(args.url, token, name, arguments)
            if status != 200:
                raise SystemExit(f"{name}: HTTP {status}")
            samples.append(ms)
        worst = max(worst, max(samples))
        ok = "✅" if max(samples) <= BUDGET_MS else "❌"
        print(f"| `{name}` | {statistics.median(samples):.0f} | {max(samples):.0f} | {ok} |")
    print(f"\nWorst: {worst:.0f} ms over {args.rounds} rounds per tool.")


if __name__ == "__main__":
    main()
