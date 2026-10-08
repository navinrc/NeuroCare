import time

from conftest import NOW, USER

from alexa_mcp_server import semantic, vectors
from alexa_mcp_server.llm.fake import FakeEmbedder
from alexa_mcp_server.pillars import memory
from alexa_mcp_server.refine import Deps, InlineRefiner
from alexa_mcp_server.store.base import user_pk

SIMILAR = [("dinner with mom", "The family meal is on Sunday at grandma's house")]


def test_vector_roundtrip_and_cosine():
    v = [0.25, -0.5, 1.0]
    assert vectors.unpack(vectors.pack(v)) == v
    assert abs(vectors.cosine(v, v) - 1) < 1e-9
    assert vectors.cosine([1, 0], [0, 1]) == 0


def test_fake_embedder_groups():
    emb = FakeEmbedder(similar=[("a b", "c d")])
    assert vectors.cosine(emb.embed("a b"), emb.embed("C D!")) > 0.95
    assert abs(vectors.cosine(emb.embed("a b"), emb.embed("unrelated"))) < 0.3


def test_recall_embedding_tier_with_backfill(seeded):
    memory.remember(seeded, USER, "The family meal is on Sunday at grandma's house", NOW)
    emb = FakeEmbedder(similar=SIMILAR)

    assert memory.recall(seeded, USER, "dinner with mom", NOW)["matches"] == []  # no embedder → stops at fuzzy

    result = memory.recall(seeded, USER, "dinner with mom", NOW, embedder=emb)
    assert result["matches"][0]["text"] == "The family meal is on Sunday at grandma's house"
    assert result["matches"][0]["resolution"] == "embedding"
    # every scanned item was backfilled, so the next scan embeds only the query
    assert all(m.get("embedding") for m in seeded.query(user_pk(USER), "MEM#"))
    calls = len(emb.calls)
    memory.recall(seeded, USER, "dinner with mom", NOW, embedder=emb)
    assert len(emb.calls) == calls + 1


def test_embedding_tier_respects_consent_and_failures(seeded):
    memory.remember(seeded, USER, "The family meal is on Sunday at grandma's house", NOW)
    memory.set_preference(seeded, USER, "consent.embeddings", False, NOW)
    emb = FakeEmbedder(similar=SIMILAR)
    assert memory.recall(seeded, USER, "dinner with mom", NOW, embedder=emb)["matches"] == []
    assert emb.calls == []

    memory.set_preference(seeded, USER, "consent.embeddings", True, NOW)
    assert memory.recall(seeded, USER, "dinner with mom", NOW, embedder=FakeEmbedder(fail=True))["matches"] == []


def test_embedding_tier_stays_inside_budget(seeded):
    class Slow(FakeEmbedder):
        def embed(self, text):
            time.sleep(0.5)
            return super().embed(text)

    started = time.perf_counter()
    tier = semantic.matcher(seeded, Slow(), lambda i: i.get("text", ""))
    assert tier("dinner with mom", seeded.query(user_pk(USER), "MEM#")) == []
    assert time.perf_counter() - started < 0.35


def test_remember_embeds_on_write_via_refine_job(store):
    emb = FakeEmbedder()
    refiner = InlineRefiner(Deps(store=store, llm=None, embedder=emb, clock=lambda: NOW))
    saved = memory.remember(store, USER, "Pick up the dry cleaning", NOW, refiner=refiner)
    item = store.get(user_pk(USER), saved["id"])
    assert vectors.unpack(item["embedding"]) == vectors.unpack(vectors.pack(emb.embed("Pick up the dry cleaning")))
    person = memory.remember(store, USER, "Lee is my dentist", NOW, kind="person", subject="Lee", refiner=refiner)
    assert store.get(user_pk(USER), person["id"])["embedding"]


def test_close_loop_embedding_tier(seeded):
    emb = FakeEmbedder(similar=[("sorted the venue thing", "Reply to Jordan about the venue")])
    result = memory.close_loop(seeded, USER, "sorted the venue thing", NOW, embedder=emb)
    assert result["closed"]["text"] in ("Reply to Jordan about the venue",)
