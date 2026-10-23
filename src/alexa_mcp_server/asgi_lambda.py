"""Run an ASGI app on AWS Lambda behind a Function URL (payload format 2.0).

The ASGI lifespan is entered once per container, not per request: the MCP SDK's session manager can
only start once, and per-request startup would waste the warm-Lambda latency budget. One event loop
lives for the container; each request runs on it. No side effects on import.
"""

import asyncio
import base64
from typing import Any
from urllib.parse import unquote

ASGIApp = Any
_TEXT_TYPES = ("application/json", "text/", "application/problem+json")


class LambdaASGI:
    """Runs an ASGI app for Lambda Function URL events (payload format 2.0)."""

    def __init__(self, app: ASGIApp):
        self._app = app
        self._loop = asyncio.new_event_loop()
        self._state: dict[str, Any] = {}
        self._lifespan: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Enter the app's lifespan; it stays open for the life of the container."""
        if self._lifespan is not None:
            return
        started: asyncio.Future[None] = self._loop.create_future()
        self._lifespan = self._loop.create_task(self._run_lifespan(started))
        self._loop.run_until_complete(started)

    async def _run_lifespan(self, started: asyncio.Future[None]) -> None:
        messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        messages.put_nowait({"type": "lifespan.startup"})

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "lifespan.startup.complete":
                started.set_result(None)
            elif message["type"] == "lifespan.startup.failed":
                started.set_exception(RuntimeError(message.get("message", "lifespan startup failed")))

        scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}, "state": self._state}
        await self._app(scope, messages.get, send)

    def __call__(self, event: dict[str, Any]) -> dict[str, Any]:
        self.start()
        return self._loop.run_until_complete(self._http(event))

    async def _http(self, event: dict[str, Any]) -> dict[str, Any]:
        context = event["requestContext"]
        http = context["http"]
        raw_path = event.get("rawPath") or http.get("path") or "/"
        headers = [(k.lower().encode("latin-1"), str(v).encode("latin-1")) for k, v in event.get("headers", {}).items()]
        if event.get("cookies"):
            headers.append((b"cookie", "; ".join(event["cookies"]).encode("latin-1")))
        body = event.get("body") or ""
        payload = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": http["method"],
            "scheme": "https",
            "path": unquote(raw_path),
            "raw_path": raw_path.encode(),
            "query_string": (event.get("rawQueryString") or "").encode(),
            "root_path": "",
            "headers": headers,
            "client": (http.get("sourceIp", ""), 0),
            "server": (context.get("domainName", "lambda"), 443),
            "state": dict(self._state),
        }

        done = asyncio.Event()
        sent_body = False

        async def receive() -> dict[str, Any]:
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": payload, "more_body": False}
            await done.wait()  # the client "disconnects" only once the response is complete
            return {"type": "http.disconnect"}

        status = 500
        out_headers: list[tuple[bytes, bytes]] = []
        chunks: list[bytes] = []

        async def send(message: dict[str, Any]) -> None:
            nonlocal status, out_headers
            if message["type"] == "http.response.start":
                status, out_headers = message["status"], list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    done.set()

        try:
            await self._app(scope, receive, send)
        finally:
            done.set()
        return _response(status, out_headers, b"".join(chunks))


def _response(status: int, raw_headers: list[tuple[bytes, bytes]], body: bytes) -> dict[str, Any]:
    headers: dict[str, str] = {}
    cookies: list[str] = []
    for key, value in raw_headers:
        name, text = key.decode("latin-1").lower(), value.decode("latin-1")
        if name == "set-cookie":
            cookies.append(text)
        else:
            headers[name] = f"{headers[name]}, {text}" if name in headers else text
    content_type = headers.get("content-type", "")
    is_text = not body or any(content_type.startswith(t) for t in _TEXT_TYPES)
    result: dict[str, Any] = {
        "statusCode": status,
        "headers": headers,
        "body": body.decode() if is_text else base64.b64encode(body).decode(),
        "isBase64Encoded": not is_text,
    }
    if cookies:
        result["cookies"] = cookies
    return result
