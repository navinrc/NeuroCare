"""Fast first, refine later (spec §4).

A tool stores its deterministic baseline, returns it, and submits a refine job. The job runs the
LLM call off the request path and writes the refined result back onto the stored item.

Jobs are registered by name with ``@job`` and run as ``fn(deps, user_id, ref)`` where ``ref`` is the
item's sort key. Runners:

- ``InlineRefiner``: runs the job before returning (Telegram webhook, tests).
- ``ThreadRefiner``: a background thread pool (local server).
- Lambda self-invoke (``InvocationType=Event``) arrives with the AWS deploy in phase 6.
"""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from alexa_mcp_server.llm import LLM, Embedder
from alexa_mcp_server.store.base import Store

log = logging.getLogger(__name__)

LLM_TIMEOUT = 5.0
"""Seconds a refine waits for the model (spec §4)."""


@dataclass
class Deps:
    """What a refine job needs. ``clock`` gives the current time (tests inject a fixed one)."""

    store: Store
    llm: LLM | None
    embedder: Embedder | None
    clock: Callable[[], datetime]
    guard: Any = None
    """``safety.crisis.Guard`` for the background crisis re-check (Bedrock Guardrails)."""


Job = Callable[[Deps, str, str], None]
JOBS: dict[str, Job] = {}


def job(name: str) -> Callable[[Job], Job]:
    def register(fn: Job) -> Job:
        JOBS[name] = fn
        return fn

    return register


def run_job(deps: Deps, name: str, user_id: str, ref: str) -> None:
    try:
        JOBS[name](deps, user_id, ref)
    except Exception:  # a failed refine must never surface to the caller; the baseline stands
        log.exception("refine job %s failed", name)


class Refiner(Protocol):
    def submit(self, name: str, user_id: str, ref: str) -> None: ...


@dataclass
class InlineRefiner:
    deps: Deps

    def submit(self, name: str, user_id: str, ref: str) -> None:
        run_job(self.deps, name, user_id, ref)


@dataclass
class ThreadRefiner:
    deps: Deps
    workers: int = 2
    _pool: ThreadPoolExecutor = field(init=False)
    _pending: set[Future[Any]] = field(init=False, default_factory=set)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="refine")

    def submit(self, name: str, user_id: str, ref: str) -> None:
        future = self._pool.submit(run_job, self.deps, name, user_id, ref)
        with self._lock:
            self._pending.add(future)
        future.add_done_callback(self._done)

    def _done(self, future: Future[Any]) -> None:
        with self._lock:
            self._pending.discard(future)

    def wait(self, timeout: float | None = None) -> None:
        """Block until every submitted job has finished (tests, shutdown)."""
        with self._lock:
            pending = set(self._pending)
        wait(pending, timeout=timeout)
