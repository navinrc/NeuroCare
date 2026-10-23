from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
import yaml
from moto import mock_aws

from alexa_mcp_server import server
from alexa_mcp_server.pillars import memory
from alexa_mcp_server.refine import Deps, InlineRefiner
from alexa_mcp_server.store import DynamoStore, SQLiteStore

NOW = datetime(2026, 10, 5, 18, 10, tzinfo=UTC)  # 2:10 PM in America/New_York
USER = "demo"
SEED = yaml.safe_load((Path(__file__).parents[1] / "profile_seed.yaml").read_text())


TABLE = "cognitive-substrate"


def create_table(name: str = TABLE) -> None:
    """The table as the CDK stack defines it (spec §8)."""
    boto3.client("dynamodb", region_name="us-east-1").create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def aws(monkeypatch):
    """moto-backed AWS with fake credentials, so nothing reaches a real account."""
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        yield


@pytest.fixture(params=["sqlite", "dynamo"])
def backend(request):
    """Every test that takes ``store`` runs on both backends (spec §11 test approach)."""
    return request.param


@pytest.fixture
def store(backend, request):
    if backend == "sqlite":
        return SQLiteStore(":memory:", clock=NOW.timestamp)
    request.getfixturevalue("aws")
    create_table()
    return DynamoStore(TABLE, clock=NOW.timestamp)


@pytest.fixture
def seeded(store):
    memory.seed(store, USER, SEED, NOW)
    return store


@pytest.fixture
def mcp_store(store, monkeypatch):
    """The MCP server wired to an in-memory store and a fixed clock."""
    monkeypatch.setattr(server, "_store", store)
    monkeypatch.setattr(server, "clock", lambda: NOW)
    deps = Deps(store=store, llm=None, embedder=None, clock=lambda: NOW)
    monkeypatch.setattr(server, "_refiner", InlineRefiner(deps))
    return store
