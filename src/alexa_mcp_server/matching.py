"""Tiered text matching for recall and close_loop (spec §3 "Recall matching").

Tiers run in order and the first tier with any hit wins: exact → alias → fuzzy. The embedding
tier is skipped until phase 3 (no Bedrock client yet).
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from alexa_mcp_server.store.base import Item

Resolution = Literal["exact", "alias", "fuzzy", "embedding"]

FUZZY_THRESHOLD = 0.6
"""Minimum fuzzy score for recall / close_loop."""
DEDUP_THRESHOLD = 0.85
"""Minimum whole-text similarity for ``remember`` to update instead of insert."""
TOKEN_MATCH = 0.85
"""Two words count as the same word above this similarity (catches typos and plurals)."""

_STOPWORDS = frozenset(
    "a an the to of and or for on in at by with about my your i me you is are was be it that this "
    "what when did do does told tell said".split()
)


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t not in _STOPWORDS]


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def fuzzy_score(query: str, text: str) -> float:
    """Share of query words found (approximately) in ``text``, or whole-string similarity if higher."""
    q_tokens = tokens(query)
    t_tokens = tokens(text)
    whole = similarity(query, text)
    if not q_tokens or not t_tokens:
        return whole
    hits = sum(1 for q in q_tokens if any(SequenceMatcher(None, q, t).ratio() >= TOKEN_MATCH for t in t_tokens))
    return max(whole, hits / len(q_tokens))


def _contains_phrase(haystack: str, phrase: str) -> bool:
    phrase = normalize(phrase)
    return bool(phrase) and re.search(rf"\b{re.escape(phrase)}\b", normalize(haystack)) is not None


@dataclass
class Match:
    item: Item
    score: float


def tiered_match(
    query: str,
    items: Sequence[Item],
    people: Mapping[str, Iterable[str]] = {},
    text_of: Callable[[Item], str] = lambda item: item.get("text", ""),
) -> tuple[Resolution | None, list[Match]]:
    """Match ``query`` against ``items``; ``people`` maps a canonical name to its aliases.

    Exact and alias hits come back newest first; fuzzy hits best first.
    """
    if not normalize(query):
        return None, []
    newest_first = sorted(items, key=lambda item: (item.get("created_at") or "", item["sk"]), reverse=True)

    exact = [
        Match(item, 1.0)
        for item in newest_first
        if _contains_phrase(text_of(item), query) or normalize(item.get("subject") or "") == normalize(query)
    ]
    if exact:
        return "exact", exact

    # A name or alias spoken in the query → items about that person.
    hit_names: set[str] = set()
    for canonical, aliases in people.items():
        names = [canonical, *aliases]
        if any(_contains_phrase(query, name) for name in names):
            hit_names.update(normalize(n) for n in names)
    if hit_names:
        alias = [
            Match(item, 1.0)
            for item in newest_first
            if normalize(item.get("subject") or "") in hit_names
            or any(_contains_phrase(text_of(item), name) for name in hit_names)
        ]
        if alias:
            return "alias", alias

    scored = [Match(item, fuzzy_score(query, text_of(item))) for item in newest_first]
    fuzzy = sorted((m for m in scored if m.score >= FUZZY_THRESHOLD), key=lambda m: m.score, reverse=True)
    if fuzzy:
        return "fuzzy", fuzzy
    return None, []
