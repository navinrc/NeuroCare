"""AWS Lambda entry point (spec §9).

Routes three kinds of event:

- Function URL requests (payload v2) go to the MCP ASGI app, served in stateless HTTP mode with
  JSON responses (spec §3).
- ``{"refine": {"name", "user_id", "ref"}}`` is the async self-invoke from ``LambdaRefiner`` and runs
  one refine job (spec §4).
- Anything else (the phase 6b scheduler) is logged and ignored for now.

The Function URL → ASGI adapter lives in ``asgi_lambda`` (no side effects on import), so the
simulator's handler can reuse it without starting this server.
"""

import logging
import os
from typing import Any
from urllib.parse import urlparse

import boto3

from alexa_mcp_server.asgi_lambda import LambdaASGI

log = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO)


def _resolve_public_base_url() -> None:
    """``PUBLIC_BASE_URL`` from the function's own URL when the stack doesn't set it.

    The Function URL exists only after the function, so CloudFormation cannot pass it in as an
    environment variable without a cycle. One ``GetFunctionUrlConfig`` call during init fixes that.
    """
    name = os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    if os.getenv("PUBLIC_BASE_URL") or not name:
        return
    url = boto3.client("lambda").get_function_url_config(FunctionName=name)["FunctionUrl"]
    os.environ["PUBLIC_BASE_URL"] = url.rstrip("/")


def build_app() -> LambdaASGI:
    from mcp.server.transport_security import TransportSecuritySettings

    from alexa_mcp_server import server

    base = server.settings.public_base_url
    host = urlparse(base).netloc
    app = server.mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=[host], allowed_origins=[base]),
        host="0.0.0.0",
    )
    server.warm()
    return LambdaASGI(app)


_app: LambdaASGI | None = None


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any] | None:
    global _app
    if "refine" in event:
        from alexa_mcp_server import server
        from alexa_mcp_server.refine import run_job

        job = event["refine"]
        run_job(server.deps(), job["name"], job["user_id"], job["ref"])
        return None
    if "requestContext" in event and "http" in event["requestContext"]:
        if _app is None:
            _app = build_app()
            _app.start()
        return _app(event)
    log.info("ignored event with keys %s", sorted(event))
    return None


if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):  # Lambda init: resolve the URL and start up before the first request
    _resolve_public_base_url()
    _app = build_app()
    _app.start()
