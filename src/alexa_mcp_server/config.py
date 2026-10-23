"""Environment settings."""

import os
from dataclasses import dataclass


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    store: str = "sqlite"
    sqlite_path: str = ".data/neurocare.sqlite3"
    table_name: str = "cognitive-substrate"
    auth_token: str = ""
    allow_static_token: bool = False
    demo_user_id: str = "demo"
    public_base_url: str = "http://127.0.0.1:8000"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    cognito_domain: str = ""
    """Hosted UI domain, e.g. ``neurocare-demo.auth.us-east-1.amazoncognito.com`` (docs only; Alexa uses it)."""
    cognito_scope: str = ""
    """Scope every Cognito access token must carry, e.g. ``neurocare/tools``; empty skips the check."""
    host: str = "127.0.0.1"
    port: int = 8000
    llm_provider: str = "off"
    """``bedrock`` to call Amazon Bedrock; ``off`` keeps every language task on its deterministic baseline."""
    bedrock_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    bedrock_embed_model_id: str = "amazon.titan-embed-text-v2:0"
    aws_region: str = "us-east-1"
    bedrock_guardrail_id: str = ""
    bedrock_guardrail_version: str = "DRAFT"
    lambda_function_name: str = ""
    """Set by Lambda (``AWS_LAMBDA_FUNCTION_NAME``); refines then run as an async self-invoke."""


def load_settings() -> Settings:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    return Settings(
        store=os.getenv("STORE", "sqlite"),
        sqlite_path=os.getenv("SQLITE_PATH", ".data/neurocare.sqlite3"),
        table_name=os.getenv("TABLE_NAME", Settings.table_name),
        auth_token=os.getenv("AUTH_TOKEN", ""),
        allow_static_token=_flag("ALLOW_STATIC_TOKEN"),
        demo_user_id=os.getenv("DEMO_USER_ID", "demo"),
        public_base_url=os.getenv("PUBLIC_BASE_URL", f"http://{host}:{port}").rstrip("/"),
        cognito_user_pool_id=os.getenv("COGNITO_USER_POOL_ID", ""),
        cognito_client_id=os.getenv("COGNITO_CLIENT_ID", ""),
        cognito_domain=os.getenv("COGNITO_DOMAIN", ""),
        cognito_scope=os.getenv("COGNITO_SCOPE", ""),
        host=host,
        port=port,
        llm_provider=os.getenv("LLM_PROVIDER", "off").strip().lower(),
        bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", Settings.bedrock_model_id),
        bedrock_embed_model_id=os.getenv("BEDROCK_EMBED_MODEL_ID", Settings.bedrock_embed_model_id),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        bedrock_guardrail_id=os.getenv("BEDROCK_GUARDRAIL_ID", ""),
        bedrock_guardrail_version=os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
        lambda_function_name=os.getenv("AWS_LAMBDA_FUNCTION_NAME", ""),
    )
