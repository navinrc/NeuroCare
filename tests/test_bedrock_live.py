"""Real Bedrock calls (spec §11 phases 3–4). Skipped unless BEDROCK_LIVE=1 and AWS credentials are set:

BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin uv run pytest -m live -s

The guardrail tests also need BEDROCK_GUARDRAIL_ID (and BEDROCK_GUARDRAIL_VERSION, default DRAFT).
"""

import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from conftest import NOW, USER

from alexa_mcp_server import semantic, vectors
from alexa_mcp_server.config import load_settings
from alexa_mcp_server.llm.bedrock import BedrockEmbedder, BedrockGuard, BedrockLLM
from alexa_mcp_server.pillars import guardrail, memory, translator
from alexa_mcp_server.refine import Deps, InlineRefiner
from alexa_mcp_server.safety import crisis
from alexa_mcp_server.store import SQLiteStore
from alexa_mcp_server.store.base import user_pk

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("BEDROCK_LIVE") != "1", reason="set BEDROCK_LIVE=1 to call Amazon Bedrock"),
]
needs_guardrail = pytest.mark.skipif(not os.getenv("BEDROCK_GUARDRAIL_ID"), reason="set BEDROCK_GUARDRAIL_ID")

SELF_HARM = "Lately I feel like there's no point in being here at all"  # not on the phrase list
ORDINARY = "Bring snacks to the offsite"


def test_live_decode_refine():
    settings = load_settings()
    llm = BedrockLLM(settings.bedrock_model_id, settings.aws_region)
    store = SQLiteStore(":memory:")
    now = datetime.now(UTC)
    refiner = InlineRefiner(Deps(store=store, llm=llm, embedder=None, clock=lambda: now))
    result = translator.decode(
        store, "live", now, message="Per my last email, can you send the deck today? Thanks, Priya", refiner=refiner
    )
    print(result)
    assert result["refine"] == "done", result
    assert result["summary"] and result["likely_intents"]


def test_live_embedding():
    settings = load_settings()
    emb = BedrockEmbedder(settings.bedrock_embed_model_id, settings.aws_region)
    a, b, c = emb.embed("dinner with mom"), emb.embed("family meal on Sunday"), emb.embed("quarterly tax filing")
    print(vectors.cosine(a, b), vectors.cosine(a, c))
    assert len(a) == 1024
    assert vectors.cosine(a, b) > vectors.cosine(a, c)


def _guard():
    settings = load_settings()
    return BedrockGuard(settings.bedrock_guardrail_id, settings.bedrock_guardrail_version, settings.aws_region)


def _timed(fn, *args):
    start = time.perf_counter()
    value = fn(*args)
    return value, (time.perf_counter() - start) * 1000


@needs_guardrail
def test_live_guard_intervenes_on_self_harm_only():
    guard = _guard()
    assert not crisis.phrase_hit(SELF_HARM)  # so the hit below comes from Bedrock
    hit, cold_ms = _timed(guard.intervenes, SELF_HARM)
    clear, warm_ms = _timed(guard.intervenes, ORDINARY)
    print(f"ApplyGuardrail: cold {cold_ms:.0f} ms, warm {warm_ms:.0f} ms (budget {crisis.GUARD_BUDGET * 1000:.0f} ms)")
    assert hit is True
    assert clear is False


@needs_guardrail
def test_live_remember_precheck_catches_self_harm(seeded):
    # Inline refiner: a guard timeout re-runs the check before remember stores the text.
    guard = _guard()
    now = NOW  # matches the seeded store's clock
    refiner = InlineRefiner(Deps(store=seeded, llm=None, embedder=None, clock=lambda: now, guard=guard))
    result = memory.remember(seeded, USER, SELF_HARM, now, refiner=refiner, guard=guard)
    flagged = crisis.pending_flag(seeded, USER, now)
    print("immediate crisis" if result.get("crisis") else f"async hit, flagged next call: {flagged is not None}")
    assert result.get("crisis") or flagged
    assert not any("no point" in str(i) for i in seeded.query(user_pk(USER), ""))

    kept = memory.remember(seeded, USER, ORDINARY, now, refiner=refiner, guard=guard)
    assert "crisis" not in kept
    assert crisis.pending_flag(seeded, USER, now) is None


def test_live_rumination_by_embedding(seeded, monkeypatch):
    settings = load_settings()
    emb = BedrockEmbedder(settings.bedrock_embed_model_id, settings.aws_region)
    # Few shared words, so Jaccard stays under 0.5 and only the cosine can match them.
    phrasings = [
        "the presentation tomorrow",
        "is my presentation going to be ok",
        "what if my presentation goes badly",
    ]
    assert all(guardrail.jaccard(a, b) < guardrail.JACCARD_MIN for a in phrasings for b in phrasings if a != b)
    vecs = [emb.embed(t) for t in phrasings]
    print(
        "Titan cosines:",
        [round(vectors.cosine(a, b), 3) for i, a in enumerate(vecs) for b in vecs[i + 1 :]],
        f"min {guardrail.COSINE_MIN}",
    )

    # Outside AWS the round trip alone exceeds the 200 ms embed budget; this checks the threshold, not latency.
    monkeypatch.setattr(semantic, "EMBED_BUDGET", 5.0)
    now = NOW  # matches the seeded store's clock
    refiner = InlineRefiner(Deps(store=seeded, llm=None, embedder=emb, clock=lambda: now))
    results = [
        guardrail.log_topic(seeded, USER, t, now + timedelta(minutes=i), embedder=emb, refiner=refiner)
        for i, t in enumerate(phrasings)
    ]
    print([(r["count"], r["detected"]) for r in results])
    assert results[-1]["detected"] is True
