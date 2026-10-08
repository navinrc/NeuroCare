"""Issue or revoke the demo user's inbox token for local dev: ``uv run alexa-mcp-inbox-token [--revoke]``.

In production the Telegram bot issues it with ``/token`` (phase 6b).
"""

import argparse
from datetime import UTC, datetime

from alexa_mcp_server.config import load_settings
from alexa_mcp_server.pillars import inbox
from alexa_mcp_server.store import make_store


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revoke", action="store_true", help="revoke every inbox token for the demo user")
    args = parser.parse_args()
    settings = load_settings()
    store = make_store(settings)
    if args.revoke:
        print(f"Revoked {inbox.revoke_inbox_tokens(store, settings.demo_user_id)} token(s).")
        return
    token = inbox.issue_inbox_token(store, settings.demo_user_id, datetime.now(UTC))
    print(f"Inbox token for {settings.demo_user_id!r} (shown once):\n{token}")


if __name__ == "__main__":
    main()
