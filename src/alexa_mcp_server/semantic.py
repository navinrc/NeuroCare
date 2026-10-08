"""Embedding tier for recall and rumination (spec §3, §8).

Vectors are stored on the item as base64 float32 (``embedding``). New items are embedded by the
``embed`` refine job after they are written; items still at ``embedding: null`` are backfilled the
first time this tier scans them, as far as the latency budget allows.
"""

import time
from collections.abc import Callable, Sequence

from alexa_mcp_server import vectors
from alexa_mcp_server.llm import Embedder, LLMError, within
from alexa_mcp_server.matching import Match
from alexa_mcp_server.refine import Deps, job
from alexa_mcp_server.store.base import Item, Store, user_pk

EMBED_THRESHOLD = 0.5
"""Minimum cosine for an embedding-tier hit."""
EMBED_BUDGET = 0.2
"""Seconds the tier may spend on the Alexa path (query embedding + backfill), spec §4."""


def item_vector(item: Item) -> list[float] | None:
    blob = item.get("embedding")
    return vectors.unpack(blob) if blob else None


def store_vector(store: Store, item: Item, vector: list[float]) -> None:
    store.put(item["pk"], item["sk"], {**item, "embedding": vectors.pack(vector)})


def matcher(
    store: Store, embedder: Embedder | None, text_of: Callable[[Item], str], budget: float = EMBED_BUDGET
) -> Callable[[str, Sequence[Item]], list[Match]] | None:
    """A ``semantic`` tier for ``tiered_match``, or ``None`` when there is no embedder."""
    if embedder is None:
        return None

    def tier(query: str, items: Sequence[Item]) -> list[Match]:
        deadline = time.monotonic() + budget
        try:
            query_vector = within(budget, embedder.embed, query)
        except (TimeoutError, LLMError):
            return []
        hits = []
        for item in items:
            vector = item_vector(item)
            if vector is None:
                left = deadline - time.monotonic()
                if left <= 0:
                    continue  # backfilled on a later scan
                try:
                    vector = within(left, embedder.embed, text_of(item))
                except (TimeoutError, LLMError):
                    continue
                store_vector(store, item, vector)
            score = vectors.cosine(query_vector, vector)
            if score >= EMBED_THRESHOLD:
                hits.append(Match(item, score))
        return sorted(hits, key=lambda m: m.score, reverse=True)

    return tier


@job("embed")
def embed_item(deps: Deps, user_id: str, ref: str) -> None:
    """Embed one item after it was written (``MEM#``, ``PERSON#``, ``TOPIC#``)."""
    if deps.embedder is None:
        return
    item = deps.store.get(user_pk(user_id), ref)
    if item is None:
        return
    text = item.get("text") or ". ".join([item.get("name", ""), *item.get("notes", [])])
    store_vector(deps.store, item, deps.embedder.embed(text))
