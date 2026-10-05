"""Time-ordered ULIDs (Crockford base32, 26 chars)."""

import os
import threading
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_lock = threading.Lock()
_last_ms = 0
_last_rand = 0


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))


def new_ulid() -> str:
    """Monotonic within a process: ids made in the same millisecond still sort in creation order."""
    global _last_ms, _last_rand
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            ms = _last_ms
            rand = _last_rand + 1
        else:
            rand = int.from_bytes(os.urandom(10))
        _last_ms, _last_rand = ms, rand
    return _encode(ms, 10) + _encode(rand & ((1 << 80) - 1), 16)
