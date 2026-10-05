"""Load the demo seed into the configured store: ``uv run alexa-mcp-seed [path] [--reset]``."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

import yaml

from alexa_mcp_server.config import load_settings
from alexa_mcp_server.pillars import memory
from alexa_mcp_server.store import make_store
from alexa_mcp_server.store.base import user_pk


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="profile_seed.yaml")
    parser.add_argument("--reset", action="store_true", help="delete the demo user's data first")
    args = parser.parse_args()

    settings = load_settings()
    store = make_store(settings)
    user_id = settings.demo_user_id
    if args.reset:
        store.delete_partition(user_pk(user_id))
    elif store.get(user_pk(user_id), "PROFILE"):
        raise SystemExit(f"User {user_id!r} already has data; pass --reset to replace it.")

    data = yaml.safe_load(Path(args.path).read_text())
    counts = memory.seed(store, user_id, data, datetime.now(UTC))
    print(f"Seeded {user_id!r}: " + ", ".join(f"{n} {k}" for k, n in counts.items()))


if __name__ == "__main__":
    main()
