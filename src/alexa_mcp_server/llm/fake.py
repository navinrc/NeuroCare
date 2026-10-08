"""Scripted LLM and deterministic embedder for tests (spec §11 "Test approach")."""

import hashlib
import math
import random
import time
from collections.abc import Iterable
from typing import Any

from alexa_mcp_server.llm import LLMError
from alexa_mcp_server.matching import normalize


class FakeLLM:
    """Returns scripted replies in order (the last one repeats), or raises when a reply is an exception.

    A reply can also be a callable ``(system, prompt) -> dict`` for prompt-dependent answers.
    """

    def __init__(self, *replies: Any, delay: float = 0.0):
        self.replies = list(replies) or [LLMError("no scripted reply")]
        self.delay = delay
        self.calls: list[dict[str, str]] = []

    def complete_json(self, system: str, prompt: str, *, timeout: float) -> dict[str, Any]:
        self.calls.append({"system": system, "prompt": prompt})
        if self.delay:
            time.sleep(self.delay)
            if self.delay > timeout:
                raise LLMError("timeout")
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            return reply(system, prompt)
        return dict(reply)


class FakeEmbedder:
    """Deterministic unit vectors from a text hash. Texts in the same ``similar`` group share a base
    vector (cosine ≈ 0.99); unrelated texts are near-orthogonal."""

    def __init__(self, similar: Iterable[Iterable[str]] = (), dims: int = 256, fail: bool = False):
        self.dims = dims
        self.fail = fail
        self.calls: list[str] = []
        self._group: dict[str, str] = {}
        for group in similar:
            members = [normalize(t) for t in group]
            for member in members:
                self._group[member] = members[0]

    def _vector(self, seed: str, scale: float = 1.0) -> list[float]:
        rng = random.Random(hashlib.sha256(seed.encode()).digest())
        return [rng.gauss(0, 1) * scale for _ in range(self.dims)]

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.fail:
            raise LLMError("embedder down")
        key = normalize(text)
        base = self._vector(self._group.get(key, key))
        if key in self._group:
            base = [b + n for b, n in zip(base, self._vector("noise:" + key, 0.1), strict=True)]
        norm = math.sqrt(sum(v * v for v in base))
        return [v / norm for v in base]
