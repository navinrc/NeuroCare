"""Environment settings."""

import os
from dataclasses import dataclass


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    store: str = "sqlite"
    sqlite_path: str = ".data/neurocare.sqlite3"
    auth_token: str = ""
    allow_static_token: bool = False
    demo_user_id: str = "demo"
    public_base_url: str = "http://127.0.0.1:8000"
    host: str = "127.0.0.1"
    port: int = 8000


def load_settings() -> Settings:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    return Settings(
        store=os.getenv("STORE", "sqlite"),
        sqlite_path=os.getenv("SQLITE_PATH", ".data/neurocare.sqlite3"),
        auth_token=os.getenv("AUTH_TOKEN", ""),
        allow_static_token=_flag("ALLOW_STATIC_TOKEN"),
        demo_user_id=os.getenv("DEMO_USER_ID", "demo"),
        public_base_url=os.getenv("PUBLIC_BASE_URL", f"http://{host}:{port}").rstrip("/"),
        host=host,
        port=port,
    )
