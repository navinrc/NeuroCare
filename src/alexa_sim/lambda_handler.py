"""AWS Lambda entry point for the simulator: Function URL events → the Starlette app.

Reuses the server's ``LambdaASGI`` adapter.
"""

import os
from typing import Any

import boto3

from alexa_mcp_server.asgi_lambda import LambdaASGI


def _resolve_urls() -> None:
    """``SIM_PUBLIC_URL`` from this function's URL and ``SIM_MCP_URL`` from the server function's.

    The stack can't pass either in: the Cognito client's callback URL depends on the simulator, and
    the server depends on the client, so environment references would form a cycle.
    """
    lambda_client = boto3.client("lambda")
    for env, function in (
        ("SIM_PUBLIC_URL", os.getenv("AWS_LAMBDA_FUNCTION_NAME")),
        ("SIM_MCP_URL", os.getenv("SIM_MCP_FUNCTION")),
    ):
        if os.getenv(env) or not function:
            continue
        url = lambda_client.get_function_url_config(FunctionName=function)["FunctionUrl"].rstrip("/")
        os.environ[env] = url + ("/mcp" if env == "SIM_MCP_URL" else "")


def _build() -> LambdaASGI:
    from alexa_sim.app import build_app, make_sim
    from alexa_sim.config import load_sim_settings

    app = LambdaASGI(build_app(make_sim(load_sim_settings())))
    app.start()
    return app


_app: LambdaASGI | None = None


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any] | None:
    global _app
    if _app is None:
        _app = _build()
    return _app(event)


if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):  # Lambda init
    _resolve_urls()
    _app = _build()
