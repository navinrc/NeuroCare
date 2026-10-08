"""Embedding vectors: compact storage (base64 float32, spec §8) and cosine similarity."""

import base64
import math
from array import array


def pack(vector: list[float]) -> str:
    return base64.b64encode(array("f", vector).tobytes()).decode()


def unpack(blob: str) -> list[float]:
    values = array("f")
    values.frombytes(base64.b64decode(blob))
    return values.tolist()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
