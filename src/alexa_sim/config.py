"""Simulator settings (spec §5.9)."""

import os
from dataclasses import dataclass

SCOPES = "openid email neurocare/tools"


@dataclass(frozen=True)
class SimSettings:
    mcp_url: str = "http://127.0.0.1:8000/mcp"
    model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    region: str = "us-east-1"
    cognito_domain: str = ""
    """Hosted UI domain, e.g. ``neurocare-demo-nrc.auth.us-east-1.amazoncognito.com``."""
    client_id: str = ""
    client_secret: str = ""
    user_pool_id: str = ""
    """With no client id/secret given, they are read from the pool's ``alexa-plus`` client at startup."""
    table: str = ""
    """DynamoDB table for sessions; empty keeps sessions in memory (local dev, tests)."""
    public_url: str = "http://127.0.0.1:8100"
    static_token: str = ""
    """Bearer token for a local server with ``ALLOW_STATIC_TOKEN``; skips account linking."""
    host: str = "127.0.0.1"
    port: int = 8100

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/sim/callback"

    @property
    def can_link(self) -> bool:
        return bool(self.cognito_domain and self.client_id)


def load_sim_settings() -> SimSettings:
    port = int(os.getenv("SIM_PORT", "8100"))
    host = os.getenv("SIM_HOST", "127.0.0.1")
    return SimSettings(
        mcp_url=os.getenv("SIM_MCP_URL", SimSettings.mcp_url),
        model_id=os.getenv("SIM_MODEL_ID", SimSettings.model_id),
        region=os.getenv("AWS_REGION", "us-east-1"),
        cognito_domain=os.getenv("COGNITO_DOMAIN", ""),
        client_id=os.getenv("SIM_CLIENT_ID", ""),
        client_secret=os.getenv("SIM_CLIENT_SECRET", ""),
        user_pool_id=os.getenv("COGNITO_USER_POOL_ID", ""),
        table=os.getenv("SIM_TABLE", ""),
        public_url=os.getenv("SIM_PUBLIC_URL", f"http://{host}:{port}").rstrip("/"),
        static_token=os.getenv("SIM_STATIC_TOKEN", ""),
        host=host,
        port=port,
    )
