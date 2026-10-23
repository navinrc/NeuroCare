"""DynamoDB backend: one table, ``PK``/``SK`` string keys, ``ttl`` epoch seconds (spec §8).

Documents go through JSON on the way in, as on SQLite, so both backends store the same shapes
(tuples become lists, numbers keep their JSON value). DynamoDB numbers come back as ``Decimal``;
they are turned back into ``int`` or ``float``. DynamoDB deletes expired items lazily (up to a few
days late), so reads also filter on ``ttl``. The ``ttl`` argument is stored as the table's TTL
attribute, ``ttl``; pillars that keep ``ttl`` on the document pass the same value, so reads return it.
"""

import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from alexa_mcp_server.store.base import Item, Store

_KEYS = ("PK", "SK")


def _to_dynamo(doc: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(doc), parse_float=Decimal)


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        text = str(value)
        return float(value) if "." in text or "E" in text.upper() else int(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


def _row_to_item(row: dict[str, Any]) -> Item:
    body = {k: _from_dynamo(v) for k, v in row.items() if k not in _KEYS}
    return {**body, "pk": row["PK"], "sk": row["SK"]}


class DynamoStore(Store):
    def __init__(self, table_name: str, *, region: str = "us-east-1", clock: Callable[[], float] = time.time):
        """``clock`` gives epoch seconds for TTL checks; tests pass their fixed clock."""
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self._clock = clock

    def _live(self, row: dict[str, Any]) -> bool:
        ttl = row.get("ttl")
        return ttl is None or int(ttl) > int(self._clock())

    def get(self, pk: str, sk: str) -> Item | None:
        row = self._table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
        return _row_to_item(row) if row and self._live(row) else None

    def put(self, pk: str, sk: str, doc: dict[str, Any], *, ttl: int | None = None) -> Item:
        body = {k: v for k, v in doc.items() if k not in ("pk", "sk")}
        row = {**_to_dynamo(body), "PK": pk, "SK": sk}
        if ttl is not None:
            row["ttl"] = ttl
        self._table.put_item(Item=row)
        return {**body, "pk": pk, "sk": sk}

    def _rows(self, pk: str, prefix: str = "", **extra: Any) -> list[dict[str, Any]]:
        condition = Key("PK").eq(pk)
        if prefix:
            condition &= Key("SK").begins_with(prefix)
        kwargs: dict[str, Any] = {"KeyConditionExpression": condition, **extra}
        rows: list[dict[str, Any]] = []
        while True:
            page = self._table.query(**kwargs)
            rows.extend(page["Items"])
            if "LastEvaluatedKey" not in page:
                return rows
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def query(self, pk: str, prefix: str = "") -> list[Item]:
        return [_row_to_item(row) for row in self._rows(pk, prefix) if self._live(row)]

    def delete(self, pk: str, sk: str) -> None:
        self._table.delete_item(Key={"PK": pk, "SK": sk})

    def delete_partition(self, pk: str) -> int:
        keys = self._rows(pk, ProjectionExpression="PK, SK")
        with self._table.batch_writer() as batch:
            for key in keys:
                batch.delete_item(Key={"PK": key["PK"], "SK": key["SK"]})
        return len(keys)
