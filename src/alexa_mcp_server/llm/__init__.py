"""Language-model and embedding clients (spec §3: hybrid — deterministic baseline first, LLM refine after).

Pillars depend only on the two small protocols here; ``bedrock.py`` is the AWS implementation and
``fake.py`` the scripted one used by tests.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Protocol

from alexa_mcp_server.config import Settings


class LLMError(Exception):
    """The model call failed, timed out, or returned something that isn't the JSON we asked for."""


class LLM(Protocol):
    def complete_json(self, system: str, prompt: str, *, timeout: float) -> dict[str, Any]:
        """One request; returns the parsed JSON object from the reply. Raises ``LLMError``."""
        ...


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]:
        """A unit-length vector for ``text``. Raises ``LLMError``."""
        ...


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any]:
    """The first JSON object in a model reply (tolerates code fences and stray prose)."""
    match = _JSON_OBJECT.search(text)
    if not match:
        raise LLMError("no JSON object in reply")
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON: {exc.msg}") from None
    if not isinstance(value, dict):
        raise LLMError("reply is not a JSON object")
    return value


_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="budget")


def within(budget_seconds: float, fn: Any, *args: Any) -> Any:
    """Run ``fn(*args)`` but stop waiting after the budget; raises ``TimeoutError``.

    The call keeps running in the background and its result is dropped — fine for idempotent reads.
    """
    future = _pool.submit(fn, *args)
    try:
        return future.result(timeout=budget_seconds)
    except FutureTimeout:
        raise TimeoutError(f"over {budget_seconds * 1000:.0f} ms budget") from None


def make_llm(settings: Settings) -> LLM | None:
    if settings.llm_provider == "bedrock":
        from alexa_mcp_server.llm.bedrock import BedrockLLM

        return BedrockLLM(settings.bedrock_model_id, settings.aws_region)
    return None


def make_embedder(settings: Settings) -> Embedder | None:
    if settings.llm_provider == "bedrock":
        from alexa_mcp_server.llm.bedrock import BedrockEmbedder

        return BedrockEmbedder(settings.bedrock_embed_model_id, settings.aws_region)
    return None


def make_guard(settings: Settings) -> Any:
    """A ``safety.crisis.Guard`` when a Bedrock guardrail is configured, else ``None`` (phrase list only)."""
    if settings.llm_provider == "bedrock" and settings.bedrock_guardrail_id:
        from alexa_mcp_server.llm.bedrock import BedrockGuard

        return BedrockGuard(settings.bedrock_guardrail_id, settings.bedrock_guardrail_version, settings.aws_region)
    return None
