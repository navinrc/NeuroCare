"""One real Bedrock call (spec §11 phase 3). Skipped unless BEDROCK_LIVE=1 and AWS credentials are set:

BEDROCK_LIVE=1 AWS_PROFILE=neurocare-admin uv run pytest -m live -s
"""

import os
from datetime import UTC, datetime

import pytest

from alexa_mcp_server import vectors
from alexa_mcp_server.config import load_settings
from alexa_mcp_server.llm.bedrock import BedrockEmbedder, BedrockLLM
from alexa_mcp_server.pillars import translator
from alexa_mcp_server.refine import Deps, InlineRefiner
from alexa_mcp_server.store import SQLiteStore

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("BEDROCK_LIVE") != "1", reason="set BEDROCK_LIVE=1 to call Amazon Bedrock"),
]


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
